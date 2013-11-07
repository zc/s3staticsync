""" usage: %prog [options] srcdir bucket
"""

import boto.s3.connection
import boto.s3.key
import hashlib
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
parser.add_option('-g', '--generate-index-html', action="store_true")

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

    from os.path import exists, join, dirname, isdir

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
        if not options.ignore_index and exists(options.index):
            with open(options.index) as f:
                s3 = marshal.load(f)
            had_index = True
        index = {}
    else:
        index = None

    src_path, bucket_name = args

    if '/' in bucket_name:
        bucket_name, bucket_prefix = bucket_name.split('/', 1)
    else:
        bucket_prefix = ''
    len_bucket_prefix = len(bucket_prefix)

    fs = {}
    queue = Queue.Queue(maxsize=999)
    put = queue.put

    generate_index_html = options.generate_index_html
    GENERATE = object()
    INDEX_HTML = "index.html"

    def worker(base_path):
        mtime = path = 0
        while 1:
            try:
                mtime, queued_path = queue.get()

                path = queued_path
                if path is None:
                    return

                key = boto.s3.key.Key(bucket)

                if mtime is None: # delete
                    try:
                        try:
                            key.key = bucket_prefix + path
                            key.delete()
                        except Exception:
                            logger.exception('deleting %r, retrying' % key.key)
                            time.sleep(9)
                            key.key = bucket_prefix + path
                            key.delete()
                    except Exception:
                        if index is not None:
                            # Failed to delete. Put the key back so we
                            # try again later
                            index[queued_path] = 1
                        raise

                elif mtime is GENERATE:
                    (path, s3mtime) = path
                    fspath = join(base_path, path)
                    if exists(fspath):
                        # Someone created a file since we decided to
                        # generate one.
                        continue

                    fspath = dirname(fspath)
                    data = "Index of "+path[:-len(INDEX_HTML)-1]
                    data = [
                        "<!-- generated -->",
                        "<html><head><title>%s</title></head><body>" % data,
                        "<h1>%s</h1><table>" % data,
                        "<tr><th>Name</th><th>Last modified</th><th>Size</th>"
                        "</tr>",
                        ]
                    for name in sorted(os.listdir(fspath)):
                        if name.startswith('.'):
                            continue # don't index dot files
                        name_path = join(fspath, name)
                        if isdir(name_path):
                            name = name + '/'
                            size = '-'
                        else:
                            size = os.stat(name_path).st_size
                        mtime = time.ctime(os.stat(name_path).st_mtime)
                        data.append(
                            '<tr><td><a href="%s">%s</a></td>\n'
                            '    <td>%s</td><td>%s</td></tr>'
                            % (name, name, mtime, size))
                    data.append("</table></body></html>\n")
                    data = '\n'.join(data)

                    digest = hashlib.md5(data).hexdigest()
                    if digest != s3mtime:
                        # Note that s3mtime is either a previous
                        # digest or it's 0 (cus path wasn't in s3) or
                        # it's an s3 upload time.  The test above
                        # works in all of these cases.
                        key.key = bucket_prefix + path
                        key.set_metadata('generated', 'true')
                        try:
                            key.set_contents_from_string(
                                data,
                                headers={'Content-Type': 'text/html'},
                                )
                        except Exception:
                            logger.exception('uploading generated %r, retrying'
                                             % path)
                            time.sleep(9)
                            key.set_contents_from_string(
                                data,
                                headers={'Content-Type': 'text/html'},
                                )

                    if index is not None:
                        index[path.encode(encoding)] = digest

                else: # upload
                    try:
                        if had_index:
                            # We only store mtimes to the nearest second.
                            # We don't have a fudge factor, so there's a
                            # chance that someone might update the file in
                            # the same second, so we check if a second has
                            # passed and sleep if it hasn't.
                            now = time_time_from_sixtuple(
                                time.gmtime(time.time()))
                            if not now > mtime:
                                time.sleep(1)

                        key.key = bucket_prefix + path
                        path = join(base_path, path)
                        try:
                            key.set_contents_from_filename(
                                path.encode(encoding))
                        except Exception:
                            logger.exception('uploading %r %r, retrying'
                                             % (mtime, path))
                            time.sleep(9)
                            key.set_contents_from_filename(
                                path.encode(encoding))

                    except Exception:
                        if index is not None:
                            # Upload failed. Remove from index so we
                            # try again later (if the path is still
                            # around).
                            index.pop(queued_path)
                        raise

            except Exception:
                logger.exception('processing %r %r' % (mtime, path))
            finally:
                queue.task_done()

    workers = [thread(worker, src_path)
               for i in range(options.worker_threads)]

    # As we build up the 2 dicts, we try to identify cases we can
    # eliminate right away, or cases we can begin handling, so we can
    # avoid accumulating them, and also so we can start processing
    # sooner.

    def listfs(path, base):
        for name in sorted(os.listdir(path)):
            pname = join(path, name)
            rname = join(base, name)
            if isdir(pname):
                listfs(pname, rname)
                if generate_index_html and not exists(join(pname, INDEX_HTML)):
                    key = rname.decode(encoding)+'/'+INDEX_HTML
                    # We don't short circuit by checking s3 here.
                    # We'll do that at the end.
                    fs[key] = -1
            else:
                try:
                    mtime = time_time_from_sixtuple(
                        time.gmtime(os.stat(pname).st_mtime))
                except OSError:
                    logger.exception("bad file %r" % rname)
                    continue

                key = rname.decode(encoding)
                if index is not None:
                    index[key] = mtime
                if key in s3:
                    # We can go ahead and do the check
                    s3mtime = s3.pop(key)
                    if (isinstance(s3mtime, basestring) # generated
                        or mtime > s3mtime):
                        put((mtime, key))
                else:
                    fs[key] = mtime

    fs_thread = thread(listfs, src_path, '')

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

                if path in fs:
                    mtime = fs.pop(path)
                    if mtime > s3mtime:
                        put((mtime, path))
                    elif mtime == -1:
                        # generate marker. Put it back.
                        fs[path] = -1
                else:
                    s3[path] = s3mtime

        s3_thread.join()

    fs_thread.join()

    for (path, mtime) in fs.iteritems():
        s3mtime = s3.pop(path, 0)
        if mtime == -1:
            # We generate unconditionally, because the content
            # is dynamic.  We pass aling the old s3mtime, which might
            # be an old digest to see if we actually have to update s3.
            put((GENERATE, (path, s3mtime)))
        else:
            if mtime > s3mtime:
                put((mtime, path))

    if not options.no_delete:
        for path in s3:
            put((None, path))

    queue.join()

    if index is not None:
        with open(options.index, 'w') as f:
            marshal.dump(index, f)

    if lock is not None:
        lock.close()

    for _ in workers:
        put((None, None))
    for w in workers:
        w.join()

if __name__ == '__main__':
    main()

