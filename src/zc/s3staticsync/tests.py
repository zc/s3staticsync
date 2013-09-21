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
import traceback
import random
import zope.testing.setupstack

class Bucket:

    def __init__(self):
        self.data = {}

    def __iter__(self):
        for path in sorted(self.data):
            k = Key(self)
            k.key = path
            k.data, k.metadata = self.data[path]
            yield k

class Key:

    def __init__(self, bucket):
        self.bucket = bucket
        self.metadata = {}

    def set_metadata(self, k, v):
        self.metadata[k] = unicode(v)

    def get_metadata(self, k):
        return self.metadata.get(k)

    def set_contents_from_filename(self, filename):
        with open(filename) as f:
            self.bucket.data[self.key] = f.read(), self.metadata

    def check(self, base):
        with open(os.path.join(base, self.key)) as f:
            if not f.read() == self.data:
                print 'missmatched data', self.key

    def delete(self):
        del self.bucket.data[self.key]

class S3Connection:

    def __init__(self):
        self.buckets = dict(test=Bucket())

    def get_bucket(self, name):
        return self.buckets[name]

def mkfile(path):
    d = os.path.dirname(path)
    if not os.path.exists(d):
        os.makedirs(d)
    with open(path, 'w') as f:
        f.write(''.join(chr(random.randint(0,255))
                        for i in range(random.randint(0, 1<<16))))

def exception(s):
    print s
    traceback.print_exc()

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

def test_suite():
    return doctest.DocFileSuite(
        'main.test',
        setUp=setup, tearDown=zope.testing.setupstack.tearDown)

