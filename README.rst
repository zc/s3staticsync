Yet another took for syncing files to S3
****************************************

This tool is specifically designed for syncing static web sites
managed via FTP to S3.

- Posix only.

- Efficient:

  - Need to work with millions of files (but not 10s of millions)

  - Can't wait very long.  This implies using multiple threads.

  - Not practical to compute md5s

  - known usage patterns mean we can simply use modification times.

- Addresses an insane requirement of emulating insane rewrites by
  making extra data copies. Whimper.

- Option local index avoids listing buckets, which is important for
  large buckets.

- Retry on failed AWS operations.

Basic architecture
==================

On each syncronization:

- Get {path->mtime} mapping for s3 and for local file system.

  This is done in 2 threads.

  Optionally, we can keep an index, based on the previous file scan
  and avoid scanning s3.

- Compute diff.

- Apply diff to s3

  - Configurable number of workers apply changes one by one.

  - Workers fed from queue.

- As an optimization to try to avoid creation of giant dicts,
  when building dicts, if a key is already in the other dict,
  to the comparison right away.

- To decide if files have changed, we compare file-system modification
  times and S3 object modification times. This is awkward as they
  don't match up precicely.  We end up having to add a fudge factor
  to file-system modification times to account for the fact that thay
  don't line up, as well as for clock skew.


Note on AWS keys
  You pass keys via AWS instance roles (if running in AWS), .boto
  files, keyring, or .boto files.

Changes
*******

- Added support for cloudfront invalidations.

1.0.3 (2013-11-28)
==================

- Fixed: directories with weird file names broke index generation.

1.0.2 (2013-11-08)
==================

- Fixed: index.html files included dot files.

1.0.1 (2013-11-08)
==================

- Fixed: Content-Type wasn't set for generated index.html files.

         (Also tweaked html layout to force new index.html files to be
         sent.


1.0.0 (2013-11-08)
==================

- Added generation of index.html files in S3 for directories without
  them on the file system.

- Removed simple prefix rewrites. We didn't need them.

- Fixed: the restore script didn't remove extra files from the
  destination directory.

0.9.0 (2013-11-01)
==================

Added a *simple* restore script for restoring files from S3.  It
can restore an entire directory or update a directory, syncing with
S3 based on file size.

0.8.1 (2013-10-09)
==================

Added missing retry on failed adds or deletes.

0.8.0 (2013-10-02)
==================

Added support for using a local index file to avoid lengthy bucket
scans.

Added lock-file support to avoid simultaneous syncs.

0.7.0 (2013-09-30)
==================

Added support for bucket prefixes (mainly for secondary use cases).

0.6.0 (2013-09-30)
==================

Added a -D option to disable deleting keys.

0.5.0 (2013-09-26)
==================

Implement simple prefix rewrites that duplicate keys matching certain
prefixes to the same keys but with different prefixes.

0.4.0 (2013-09-25)
==================

Fix: needed to use encoded file names when reading data from file
     system.  (We were storing them decoded and boto was using a
     different encoding when trying to read them.)


0.3.0 (2013-09-25)
==================

Decode file paths using the configured encoding, which defaults to
latin-1.

0.2.0 (2013-09-24)
==================

Refactored the way time stamps are compared.  Iterating over s3
buckets doesnt' return user-defined meta data (and it woould be too
expensive to fetch it on a case-by-case bases), so we can't capture
the original mtimes (which has a race condition the way we did it
anyway).  Instead, we now compare file-system modification times with
S3 object modification times, using a fudge factor to account for the
fact that they're not computed the same way, and for clock skew.

0.1.0 (2013-09-21)
==================

Initial release
