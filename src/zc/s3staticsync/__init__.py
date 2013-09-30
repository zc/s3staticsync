""" usage: %prog [options] srcdir bucket
"""

import boto.s3.connection
import boto.s3.key
import logging
import optparse
import os
import Queue
import sys
import threading
import time

parser = optparse.OptionParser(usage=__doc__)
parser.add_option('-w', '--worker-threads', type='int', default=9)
parser.add_option('-f', '--clock-fudge-factor', type='int', default=1200)
parser.add_option('-e', '--file-system-encoding', default='latin-1')
parser.add_option('-D', '--no-delete', action='store_true')

logger = logging.getLogger(__name__)

DELETE, PUT = 'dp'

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
    fudge = options.clock_fudge_factor
    encoding = options.file_system_encoding

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
                try:
                    mtime = time_time_from_sixtuple(
                        time.gmtime(os.stat(pname).st_mtime))
                except OSError:
                    logger.exception("bad file %r" % rname)
                    continue

                # add a fudge factor to account for crappy clocks and bias
                # caused by delat between start of upload and
                # computation of last_modified.
                mtime += fudge

                key = rname.decode(encoding)
                if key in s3:
                    # We can go ahead and do the check
                    s3mtime = s3.pop(key)
                    if mtime > s3mtime:
                        put((PUT, key))
                else:
                    fs[key] = mtime

    fs_thread = thread(listfs, path, '')

    s3conn = boto.s3.connection.S3Connection()
    bucket = s3conn.get_bucket(bucket_name)

    @thread
    def s3_thread():
        for key in bucket.list(bucket_prefix):
            s3mtime = time_time_from_sixtuple(parse_time(key.last_modified))
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
                    put((PUT, path))
            else:
                s3[path] = s3mtime

    def worker(base_path):
        while 1:
            try:
                op, path = queue.get()
                if path is None:
                    return

                key = boto.s3.key.Key(bucket)

                paths = [
                    dest + path[len(prefix):]
                    for (prefix, dest) in prefixes
                    if path.startswith(prefix)
                    ] + [path]
                if op == DELETE:
                    for path in paths:
                        key.key = bucket_prefix + path
                        key.delete()
                else:
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

    fs_thread.join()
    s3_thread.join()

    for (path, mtime) in fs.iteritems():
        s3mtime = s3.pop(path, 0)
        if mtime > s3mtime:
            put((PUT, path))

    if not options.no_delete:
        for path in s3:
            put((DELETE, path))

    queue.join()

    for _ in workers:
        put((None, None))
    for w in workers:
        w.join()

if __name__ == '__main__':
    main()

