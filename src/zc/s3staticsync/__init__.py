""" usage: %prog [options] srcdir bucket
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
parser.add_option('-f', '--clock-fudge-factor', type='int', default=1200)
parser.add_option('-e', '--file-system-encoding', default='latin-1')
parser.add_option('-D', '--no-delete', action='store_true')
parser.add_option('-i', '--index')
parser.add_option('-I', '--ignore-index', action='store_true',
                  help="List the S3 bucket rather than using the index file")
parser.add_option('-l', '--lock-file')

logger = logging.getLogger(__name__)

def thread(func, *args):
    t = threading.Thread(target=func, args=args)
    t.setDaemon(True)
    t.start()
    return t

# Sigh, time.  When iterating, boto returns S3 object modification
# times like this: u'2013-09-24T18:08:20.000Z'. We need to convert it to
# something we can compare to an of.stat(f).st_mtime and something we
# can store effeciently, because we'll end up having a lot of them in
# memory.

# Computing gmt mtimes from timetuples is kind of exciting. :( We'll
# get gmt-sixtuples and convery them to time values by ignoring DST.
# Basically, we don't care whether time times are accurate, but only
# that, if they're wrong, they're wrong by the same abount.

def parse_time(s):
    date, time = s.split('.')[0].split('T')
    return tuple(int(x) for x in (date.split('-')+time.split(':')))

zeros = 0, 0, 0
def time_time_from_sixtuple(tup):
    return int(time.mktime(tup[:6]+zeros))

def main(args=None):
    if args == None:
        args = sys.argv[1:]
        logging.basicConfig()

    options, args = parser.parse_args(args)

    if options.lock_file:
        import zc.lockfile
        lock = zc.lockfile.LockFile(options.lock_file)
    else:
        lock = None

    fudge = options.clock_fudge_factor
    encoding = options.file_system_encoding
    had_index = False
    s3 = {}
    if options.index:
        if not options.ignore_index and os.path.exists(options.index):
            with open(options.index) as f:
                s3 = marshal.load(f)
            had_index = True
        index = {}
    else:
        index = None

    prefixes = [arg.split('=') for arg in args if '=' in arg]
    dests = [dest for (prefix, dest) in prefixes]
    assert not [dest for dest in dests if not dest]

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
                mtime, path = queue.get()
                if path is None:
                    return

                key = boto.s3.key.Key(bucket)

                paths = [
                    dest + path[len(prefix):]
                    for (prefix, dest) in prefixes
                    if path.startswith(prefix)
                    ] + [path]
                if mtime is None:
                    for path in paths:
                        key.key = bucket_prefix + path
                        key.delete()
                else:
                    if had_index:
                        # We only store mtimes to the nearest second.
                        # We don't have a fudge factor, so there's a
                        # chance that someone might update the file in
                        # the same second, so we check if a second has
                        # passed and sleep if it hasn't.
                        now = time_time_from_sixtuple(time.gmtime(time.time()))
                        if not now > mtime:
                            time.sleep(1)

                    key.key = bucket_prefix + paths.pop(0)
                    path = os.path.join(base_path, path)
                    key.set_contents_from_filename(path.encode(encoding))
                    for path in paths:
                        key.copy(bucket_name, bucket_prefix + path)

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
                    mtime = time_time_from_sixtuple(
                        time.gmtime(os.stat(pname).st_mtime))
                except OSError:
                    logger.exception("bad file %r" % rname)
                    continue

                key = rname.decode(encoding)
                if key in s3:
                    # We can go ahead and do the check
                    s3mtime = s3.pop(key)
                    if mtime > s3mtime:
                        put((mtime, key))
                else:
                    fs[key] = mtime

                if index is not None:
                    index[key] = mtime

    fs_thread = thread(listfs, path, '')

    s3conn = boto.s3.connection.S3Connection()
    bucket = s3conn.get_bucket(bucket_name)

    if not had_index:
        @thread
        def s3_thread():
            for key in bucket.list(bucket_prefix):
                s3mtime = time_time_from_sixtuple(parse_time(key.last_modified))


                # subtract a fudge factor to account for crappy clocks and bias
                # caused by delat between start of upload and
                # computation of last_modified.
                s3mtime -= fudge


                path = key.key[len_bucket_prefix:]

                ##############################
                # skip rewrite destinations  #
                for dest in dests:
                    if path.startswith(dest):
                        path = ''
                        break

                if not path:
                    continue
                ##############################

                if path in fs:
                    mtime = fs.pop(path)
                    if mtime > s3mtime:
                        put((mtime, path))
                else:
                    s3[path] = s3mtime

        s3_thread.join()

    fs_thread.join()
    if index is not None:
        with open(options.index, 'w') as f:
            marshal.dump(index, f)

    for (path, mtime) in fs.iteritems():
        s3mtime = s3.pop(path, 0)
        if mtime > s3mtime:
            put((mtime, path))

    if not options.no_delete:
        for path in s3:
            put((None, path))

    queue.join()

    if lock is not None:
        lock.close()

    for _ in workers:
        put((None, None))
    for w in workers:
        w.join()

if __name__ == '__main__':
    main()

