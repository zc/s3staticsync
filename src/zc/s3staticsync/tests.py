##############################################################################
#
# Copyright (c) Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.0 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
import doctest
import mock
import os
import time
import traceback
import random
import sys
import zope.testing.setupstack

class Bucket:

    puts = deletes = gets = 0
    fail = False

    def __init__(self, connection):
        self.connection = connection
        self.data = {}

    listed = None
    def list(self, prefix=''):
        self.listed = prefix
        for path in sorted(self.data):
            if path.startswith(prefix):
                k = Key(self)
                k.key = path
                k.data, k.last_modified = self.data[path]
                yield k

    __iter__ = list

class Key:

    def __init__(self, bucket):
        self.bucket = bucket

    def set_contents_from_filename(self, filename):
        self.bucket.puts += 1

        if self.bucket.fail:
            raise ValueError("fail")

        self.last_modified = (
            "%4.4d-%2.2d-%2.2dT%2.2d:%2.2d:%2.2d.123"
            % time.gmtime(time.time())[:6]
            )
        with open(filename) as f:
            self.bucket.data[self.key] = (
                f.read(), self.last_modified)


    def get_contents_to_filename(self, filename):
        self.bucket.gets += 1

        if self.bucket.fail:
            raise ValueError("fail")

        with open(filename, 'w') as f:
            f.write(self.bucket.data[self.key][0])

    @property
    def size(self):
        return len(self.bucket.data[self.key][0])

    def check(self, base, prefix=''):
        with open(os.path.join(base, self.key[len(prefix):])) as f:
            if not f.read() == self.data:
                print 'missmatched data', self.key

    def copy(self, dest_bucket, dest_path):
        dest_bucket = self.bucket.connection.get_bucket(dest_bucket)
        dest_bucket.puts += 1
        if self.bucket.fail:
            raise ValueError("fail")
        dest_bucket.data[dest_path] = self.bucket.data[self.key]

    def delete(self):
        self.bucket.deletes += 1
        if self.bucket.fail:
            raise ValueError("fail")
        del self.bucket.data[self.key]

class S3Connection:

    def __init__(self):
        self.buckets = dict(test=Bucket(self))

    def get_bucket(self, name):
        return self.buckets[name]

def mkfile(path):
    d = os.path.dirname(path)
    if not os.path.exists(d):
        os.makedirs(d)
    with open(path, 'w') as f:
        f.write(''.join(chr(random.randint(0,255))
                        for i in range(random.randint(0, 1<<16))))
    os.utime(path, (time.time(), time.time()))

def exception(s):
    print s
    traceback.print_exc(file=sys.stdout)

def setup(test):
    zope.testing.setupstack.setUpDirectory(test)
    s3conn = S3Connection()
    zope.testing.setupstack.context_manager(
        test, mock.patch('boto.s3.connection.S3Connection',
                         side_effect=lambda : s3conn))
    zope.testing.setupstack.context_manager(
        test, mock.patch('boto.s3.key.Key', side_effect=Key))
    test.globs['mkfile'] = mkfile
    zope.testing.setupstack.context_manager(
        test, mock.patch('zc.s3staticsync.logger.exception',
                         side_effect=exception))

    test.globs['now'] = 1379885832.0
    zope.testing.setupstack.context_manager(
        test, mock.patch('time.time', side_effect=lambda : test.globs['now']))

    def sleep(s):
        test.globs['now'] += s
    zope.testing.setupstack.context_manager(
        test, mock.patch('time.sleep', side_effect=sleep))

def test_suite():
    return doctest.DocFileSuite(
        'main.test', 'restore.test',
        setUp=setup, tearDown=zope.testing.setupstack.tearDown)

