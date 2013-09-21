import boto.s3.connection
import boto.s3.key
import logging
import os
import Queue
import sys
import threading

logger = logging.getLogger(__name__)

def thread(func, *args):
    t = threading.Thread(target=func, args=args)
    t.setDaemon(True)
    t.start()
    return t

def worker(queue, base_path, bucket):
    while 1:
        try:
            mtime, path = queue.get()
            if path is None:
                return
            key = boto.s3.key.Key(bucket)
            key.key = path
            if mtime == None:
                key.delete()
            else:
                path = os.path.join(base_path, path)
                key.set_metadata('mtime', mtime)
                key.set_contents_from_filename(path)
        except Exception:
            logger.exception('processing %r %r' % (mtime, path))
        finally:
            queue.task_done()

def main(args=None):
    if args == None:
        args = sys.argv[1:]
        logging.basicConfig()

    path, bucket_name = args

    # We're going to rely below on dict's being thread safe and dict
    # ops being atomic.
    fs = {}
    s3 = {}
    queue = Queue.Queue(maxsize=999)
    put = queue.put

    # As we build up the 2 dicts, we try to identify cases we can
    # eliminate right away, or cases we can begin handling, so we can
    # avoid accumulating them, and also so we can start processing
    # sooner.

    def listfs(path, base):
        for name in sorted(os.listdir(path)):
            pname = os.path.join(path, name)
            rname = os.path.join(base, name)
            if os.path.isdir(pname):
                listfs(pname, rname)
            else:
                mtime = int(os.stat(pname).st_mtime)
                if rname in s3:
                    # We can go ahead and do the check
                    s3mtime = s3.pop(rname)
                    if mtime > s3mtime:
                        put((mtime, rname))
                else:
                    fs[rname] = mtime

    fs_thread = thread(listfs, path, '')

    s3conn = boto.s3.connection.S3Connection()
    bucket = s3conn.get_bucket(bucket_name)

    @thread
    def s3_thread():
        for key in bucket:
            s3mtime = int(key.get_metadata('mtime') or 0)
            path = key.key
            if path in fs:
                mtime = fs.pop(path)
                if mtime > s3mtime:
                    put((mtime, path))
            else:
                s3[path] = s3mtime

    nthreads = 19 # TODO: get from arg
    workers = [thread(worker, queue, path, bucket)
               for i in range(nthreads)]

    fs_thread.join()
    s3_thread.join()

    for (path, mtime) in fs.iteritems():
        if mtime > s3.pop(path, 0):
            put((mtime, path))

    for path in s3:
        put((None, path))

    queue.join()

    for _ in workers:
        put((None, None))
    for w in workers:
        w.join()

if __name__ == '__main__':
    main()

