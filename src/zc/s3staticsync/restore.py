""" usage: %prog [options] bucket destdir

Restore data from S3. Ignoring the file index, which may be out of date.
"""

import boto.s3.connection
import boto.s3.key
import logging
import optparse
import os
import marshal
import Queue
import sys
import threading
import time

parser = optparse.OptionParser(usage=__doc__)
parser.add_option('-w', '--worker-threads', type='int', default=9)
parser.add_option('-e', '--file-system-encoding', default='latin-1')

logger = logging.getLogger(__name__)

def thread(func, *args):
    t = threading.Thread(target=func, args=args)
    t.setDaemon(True)
    t.start()
    return t

DOWNLOAD, DELETE = 'download', None

def main(args=None):
    if args == None:
        args = sys.argv[1:]
        logging.basicConfig()

    options, args = parser.parse_args(args)

    encoding = options.file_system_encoding
    s3 = {}

    args = [arg for arg in args if '=' not in arg]

    path, bucket_name = args

    if '/' in bucket_name:
        bucket_name, bucket_prefix = bucket_name.split('/', 1)
    else:
        bucket_prefix = ''
    len_bucket_prefix = len(bucket_prefix)

    fs = {}
    queue = Queue.Queue(maxsize=999)
    put = queue.put

    def worker(base_path):
        while 1:
            try:
                op, queued_path = queue.get()

                path = queued_path
                if path is None:
                    return

                key = boto.s3.key.Key(bucket)

                if op is DELETE:
                    try:
                        os.remove(path)
                    except Exception:
                        raise

                else: # download
                    try:
                        key.key = bucket_prefix + path
                        path = os.path.join(base_path, path)
                        try:
                            parent = os.path.dirname(path)
                            if not os.path.exists(parent):
                                try:
                                    os.makedirs(parent)
                                except OSError:
                                    if not os.path.exists(parent):
                                        raise

                            key.get_contents_to_filename(path.encode(encoding))
                        except Exception:
                            logger.exception('downloading %r, retrying' % path)
                            time.sleep(9)
                            key.get_contents_to_filename(path.encode(encoding))

                    except Exception:
                        raise

            except Exception:
                logger.exception('processing %r %r' % (op, path))
            finally:
                queue.task_done()

    workers = [thread(worker, path)
               for i in range(options.worker_threads)]

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
                try:
                    size = os.stat(pname).st_size
                except OSError:
                    logger.exception("bad file %r" % rname)
                    continue

                key = rname.decode(encoding)
                if key in s3:
                    # We can go ahead and do the check
                    s3size = s3.pop(key)
                    if s3size != size:
                        put((DOWNLOAD, key))
                else:
                    fs[key] = size

    fs_thread = thread(listfs, path, '')

    s3conn = boto.s3.connection.S3Connection()
    bucket = s3conn.get_bucket(bucket_name)

    @thread
    def s3_thread():
        for key in bucket.list(bucket_prefix):
            s3size = key.size
            path = key.key[len_bucket_prefix:]

            if path in fs:
                size = fs.pop(path)
                if size != s3size:
                    put((DOWNLOAD, path))
            else:
                s3[path] = s3size

    s3_thread.join()

    fs_thread.join()

    for (path, s3size) in s3.iteritems():
        size = fs.pop(path, -1)
        if s3size != size:
            put((DOWNLOAD, path))

    for path in fs:
        put((DELETE, path))

    queue.join()

    for _ in workers:
        put((None, None))
    for w in workers:
        w.join()

if __name__ == '__main__':
    main()

