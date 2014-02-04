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
    fail = debug = False

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
                k.data, k.last_modified = self.data[path][:2]
                yield k

    __iter__ = list

    def get_key(self, path):
        k = Key(self)
        k.key = path
        k.data, k.last_modified, k.metadata = self.data[path]
        return k

class Key:

    def __init__(self, bucket):
        self.bucket = bucket
        self.metadata = {}

    def set_metadata(self, k, v):
        self.metadata[k] = v

    def get_metadata(self, k):
        return self.metadata[k]

    def set_contents_from_filename(self, filename):
        self.bucket.puts += 1
        if self.bucket.debug:
            print 'set_contents_from_filename', filename

        if self.bucket.fail:
            raise ValueError("fail")

        self.last_modified = (
            "%4.4d-%2.2d-%2.2dT%2.2d:%2.2d:%2.2d.123"
            % time.gmtime(time.time())[:6]
            )
        with open(filename) as f:
            self.bucket.data[self.key] = (
                f.read(), self.last_modified, self.metadata)

    def set_contents_from_string(self, data, headers):
        self.bucket.puts += 1
        if headers.items() != [('Content-Type', 'text/html')]:
            raise AssertionError("bad headers", headers)
        if self.bucket.debug:
            print 'set_contents_from_string', data, self.bucket.puts

        if self.bucket.fail:
            raise ValueError("fail")

        self.last_modified = (
            "%4.4d-%2.2d-%2.2dT%2.2d:%2.2d:%2.2d.123"
            % time.gmtime(time.time())[:6]
            )
        self.bucket.data[self.key] = data, self.last_modified, self.metadata

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

class Cloudfront:

    def create_invalidation_request(self, cfid, paths):
        print 'invalidated', cfid, paths

def mkfile(path, data=None):
    if data is None:
        data = ''.join(chr(random.randint(0,255))
                       for i in range(random.randint(0, 1<<16)))
    d = os.path.dirname(path)
    if not os.path.exists(d):
        os.makedirs(d)
        os.utime(d, (time.time(), time.time()))
    with open(path, 'w') as f:
        f.write(data)
    os.utime(path, (time.time(), time.time()))

def exception(s):
    print s
    traceback.print_exc(file=sys.stdout)

def setup(test):
    random.seed(0)
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

    zope.testing.setupstack.context_manager(
        test, mock.patch("boto.connect_cloudfront", side_effect=Cloudfront))

def test_suite():
    return doctest.DocFileSuite(
        'main.test', 'restore.test',
        setUp=setup, tearDown=zope.testing.setupstack.tearDown)

