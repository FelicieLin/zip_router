"""Linux / Python 3.6：單次 ZIP 批次，從 properties 讀取密碼並保留原始 ZIP。"""
import argparse
import fcntl
import hashlib
import logging
import os
from pathlib import Path, PurePosixPath
from datetime import datetime
import shutil
import stat
import sys
import tempfile
import uuid

# 從 properties 讀取唯一且非空的 ZIP_PASSWORD，回傳 UTF-8 位元組。
def read_password(path):
    values = []
    # 支援 UTF-8 BOM；忽略空白行與 properties 註解。
    with path.open('r', encoding='utf-8-sig') as stream:
        for line in stream:
            line = line.rstrip('\r\n')
            if not line.strip() or line.lstrip().startswith(('#', '!')):
                continue
            # 僅以第一個等號分隔，保留密碼中的等號與空白。
            key, separator, value = line.partition('=')
            if separator and key.strip() == 'ZIP_PASSWORD':
                values.append(value)
    if len(values) != 1 or not values[0]:
        raise ValueError('Expected exactly one nonempty ZIP_PASSWORD=value line')
    return values[0].encode('utf-8')


# 計算SHA-256摘要，供既有輸出與解壓內容比對。
def digest(path):
    h = hashlib.sha256()
    with open(str(path), 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.digest()


# 驗證ZIP項目的路徑與檔案類型，回傳可用的相對路徑。
def member_path(info):
    name = info.filename
    # 拒絕歧義名稱、絕對路徑與父目錄參照，限制解壓範圍。
    if not name or '\\' in name or '\x00' in name:
        raise ValueError('Unsafe ZIP member name')
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('Unsafe ZIP member: {!r}'.format(name))
    # 僅接受一般檔案、目錄或未標示 Unix 類型的項目。
    mode = (info.external_attr >> 16) & 0xffff
    kind = stat.S_IFMT(mode)
    if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise ValueError('Special ZIP member rejected: {!r}'.format(name))
    # 保留輸出鎖與暫存目錄名稱，避免 ZIP 內容占用內部工作路徑。
    if path.parts[0] == '.unzip_router.lock' or path.parts[0].startswith('.unzip-stage-'):
        raise ValueError('Reserved ZIP member name')
    return Path(*path.parts)


# 建立輸出路徑並逐層拒絕符號連結。
def destination(output, relative):
    path = output
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Output symlink rejected: {}'.format(path))
    return path


# 完整解壓並驗證後發布至 output；回傳新增及內容相同的檔案數。
def extract_one(archive, output, secret, limit, pyzipper):
    os.makedirs(str(output), exist_ok=True)
    lock_flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
    descriptor = os.open(str(output / '.unzip_router.lock'), lock_flags, 0o777)
    with os.fdopen(descriptor, 'a') as lock:
        # 以輸出目錄排他鎖協調檔案發布。
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        # 暫存區與輸出位於同一檔案系統，供硬連結發布；結束後自動清除。
        with tempfile.TemporaryDirectory(prefix='.unzip-stage-', dir=str(output)) as temporary:
            # 暫存目錄與新解壓檔案使用 0777 權限。
            os.chmod(temporary, 0o777)
            stage = Path(temporary)
            files, directories, seen = [], [], set()
            with open(str(archive), 'rb') as source:
                before = os.fstat(source.fileno())
                # 同時檢查宣告大小與實際解壓量；批次傳入的單一 ZIP 解壓總大小上限為10GiB。
                with pyzipper.AESZipFile(source, 'r') as zf:
                    infos = zf.infolist()
                    if sum(info.file_size for info in infos) > limit:
                        raise ValueError('ZIP exceeds max_uncompressed_bytes')
                    total = 0
                    # 驗證所有項目，拒絕重複的相對路徑。
                    for info in infos:
                        relative = member_path(info)
                        if str(relative) in seen:
                            raise ValueError('Duplicate ZIP member: {}'.format(relative))
                        seen.add(str(relative))
                        target = stage / relative
                        if info.is_dir():
                            os.makedirs(str(target), exist_ok=True)
                            directories.append(relative)
                            continue
                        os.makedirs(str(target.parent), exist_ok=True)
                        with zf.open(info, 'r', pwd=secret) as src, open(str(target), 'xb') as dst:
                            os.chmod(str(target), 0o777)
                            while True:
                                block = src.read(1024 * 1024)
                                if not block:
                                    break
                                total += len(block)
                                if total > limit:
                                    raise ValueError('ZIP exceeds max_uncompressed_bytes')
                                dst.write(block)
                        files.append(relative)
                # 來源大小或修改時間改變時，捨棄本次解壓結果。
                after = os.fstat(source.fileno())
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('Source ZIP changed during extraction')
            # 發布前檢查所有路徑；既有同名檔案僅接受內容完全相同者。
            new_files = []
            for relative in directories + files:
                target = destination(output, relative)
                for parent in target.parents:
                    if parent == output:
                        break
                    if parent.exists() and not parent.is_dir():
                        raise ValueError('Output parent is not a directory: {}'.format(parent))
                if relative in directories:
                    if target.exists() and not target.is_dir():
                        raise ValueError('Directory conflict: {}'.format(target))
                elif target.exists():
                    if not target.is_file() or digest(target) != digest(stage / relative):
                        raise ValueError('Different content at existing output: {}'.format(target))
                else:
                    new_files.append(relative)
            published = []
            created_dirs = []

            # 逐層建立目錄，只記錄本次新增的目錄。
            def make_output_dirs(directory):
                current = output
                for part in directory.relative_to(output).parts:
                    current = current / part
                    if current.is_symlink():
                        raise ValueError(
                            'Output symlink rejected: {}'.format(current)
                        )
                    try:
                        current.mkdir()
                    except FileExistsError:
                        if not current.is_dir():
                            raise ValueError(
                                'Output parent is not a directory: {}'.format(current)
                            )
                    else:
                        created_dirs.append(current)

            try:
                for relative in directories:
                    make_output_dirs(destination(output, relative))

                for relative in new_files:
                    target = destination(output, relative)
                    make_output_dirs(target.parent)
                    # 以硬連結發布完整檔案，避免覆蓋既有目的檔。
                    os.link(str(stage / relative), str(target))
                    published.append(target)

            # 發布失敗時，清除本次新增的檔案與空目錄。
            except Exception:
                for target in reversed(published):
                    target.unlink()

                # 先刪子目錄，再刪父目錄；不刪原本存在的目錄。
                for directory in reversed(created_dirs):
                    try:
                        directory.rmdir()
                    except OSError as cleanup_exc:
                        # 目錄非空或無法刪除時保留，並記錄原因。
                        logging.warning(
                            'OUTPUT_DIR_CLEANUP_FAIL %s: %s',
                            directory, cleanup_exc
                        )
                raise
            return len(new_files), len(files) - len(new_files)





# 掃描目錄第一層的一般ZIP檔，忽略符號連結並依檔名排序。
def scan_zip(directory):
    return sorted((p for p in directory.iterdir()
                   if p.suffix.lower() == '.zip' and p.is_file()
                   and not p.is_symlink()), key=lambda p: p.name)


# 搬移 ZIP；目的地名稱衝突時加入UUID，保留既有項目。
def move_zip(path, directory):
    target = directory / path.name
    if target.exists() or target.is_symlink():
        target = directory / '{}.{}{}'.format(path.stem, uuid.uuid4().hex, path.suffix)
    shutil.move(str(path), str(target))
    return target


# 執行單次批次：來源搬入 process，解壓成功歸檔至 archive，失敗移至 error。
def run_batch(root, pyzipper):
    source, process = root / 'source', root / 'process'
    output, archive, error = root / 'output', root / 'archive', root / 'error'
    # 固定本次來源清單；掃描後新增的 ZIP 留待下次執行。
    leftovers = scan_zip(process)
    file_list = scan_zip(source)
    logging.info('START source=%s leftovers=%s', len(file_list), len(leftovers))
    failures, successes = 0, 0
    pending = []
    # 遺留 ZIP 直接移至 error；搬移失敗即停止批次，避免混入新來源。
    for path in leftovers:
        failures += 1
        try:
            target = move_zip(path, error)
            logging.warning('LEFTOVER_ERROR_MOVE %s -> %s; previous batch incomplete',
                            path, target)
        except Exception as exc:
            logging.error('LEFTOVER_ERROR_MOVE_FAIL %s (%s): %s; batch stopped',
                          path, type(exc).__name__, exc)
            return 2
    # 完成本次來源清單的搬移後才解壓；僅處理成功搬入process的ZIP。
    for path in file_list:
        try:
            target = move_zip(path, process)
            pending.append(target)
            logging.info('MOVE %s -> %s', path, target)
        except Exception as exc:
            failures += 1
            logging.error('MOVE_FAIL %s (%s): %s', path, type(exc).__name__, exc)
    if not pending:
        logging.info('END success=0 failures=%s', failures)
        return 1 if failures else 0
    # 搬移完成後讀取密碼；設定失敗時保留process檔案並回傳 2。
    try:
        secret = read_password(root / 'conf' / 'ZIPSource.properties')
    except Exception as exc:
        logging.error('CONFIG_FAIL (%s); ZIPs retained in process', type(exc).__name__)
        return 2
    # 逐一解壓，單一 ZIP 的解壓總大小上限為 10 GiB。
    for path in pending:
        try:
            new, same = extract_one(path, output, secret, 10 * 1024 ** 3, pyzipper)
        # 解壓或輸出驗證失敗時移至 error，並繼續處理後續 ZIP。
        except Exception as exc:
            failures += 1
            logging.error('EXTRACT_FAIL %s (%s): %s', path.name, type(exc).__name__, exc)
            try:
                target = move_zip(path, error)
                logging.info('ERROR_MOVE %s -> %s', path, target)
            # 失敗 ZIP 無法搬移時，保留於 process 並記錄錯誤。
            except Exception as move_exc:
                logging.error('ERROR_MOVE_FAIL %s (%s): %s; retained in process',
                              path.name, type(move_exc).__name__, move_exc)
            continue
        # 輸出完成後保留原始 ZIP 至 archive，備份不自動清除。
        try:
            target = move_zip(path, archive)
            successes += 1
            logging.info('OK %s -> %s; output=%s new=%s identical=%s',
                         path, target, output, new, same)
        # 歸檔失敗時保留已完成的輸出；遺留 ZIP 於下次啟動移至 error。
        except Exception as exc:
            failures += 1
            logging.error('ARCHIVE_MOVE_FAIL %s (%s): %s; retained in process',
                          path.name, type(exc).__name__, exc)
    # 批次結束碼：0 為成功，1 為搬移或處理失敗。
    logging.info('END success=%s failures=%s', successes, failures)
    return 1 if failures else 0


# 初始化工作目錄與日誌，取得批次鎖後執行單次批次。
def main():
    # 預設根目錄為 bin 的上一層，可透過 --root 指定。
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    os.umask(0o000)
    try:
        for name in ('conf', 'source', 'process', 'output', 'error', 'archive', 'log'):
            (root / name).mkdir(parents=True, exist_ok=True)
        # 日誌以 UTF-8 追加至檔案並同步輸出至終端機，不自動清除。
        log_date = datetime.now().strftime('%Y%m%d')
        log_path = root / 'log' / 'zip_router_{}.log'.format(log_date)
        # 拒絕符號連結並保留既有檔案權限。
        log_descriptor = os.open(str(log_path),
                                 os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW,
                                 0o777)
        os.close(log_descriptor)
        handler = logging.FileHandler(str(log_path),
                                      mode='a', encoding='utf-8')
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s %(levelname)s %(message)s',
                            handlers=[handler, logging.StreamHandler()])
        # 同一根目錄僅允許一個批次執行；鎖已占用時回傳 2。
        descriptor = os.open(str(root / 'log' / '.zip_router.lock'),
                             os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o777)
        with os.fdopen(descriptor, 'a') as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                logging.error('Another batch is running')
                return 2
            import pyzipper
            return run_batch(root, pyzipper)
    # 初始化或未處理例外統一記錄，並以結束碼 2 回報。
    except Exception as exc:
        logging.error('STARTUP_FAIL (%s): %s', type(exc).__name__, exc)
        return 2


if __name__ == '__main__':
    sys.exit(main())
