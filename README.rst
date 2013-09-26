Yet another took for syncing files to S3
****************************************

Why? It was easier to write the tool I needed than to figure out
if existing tools did what I needed (sad, I know).  I actually did
look at existing tools, but they didn't appear to be scalable enough
for my use case.

This tool is specifically designed for syncing static web sites
managed via FTP to S3.

- Posix (don't need windows support)

- Efficient:

  - Need to work with millions of files (but not 10s of millions)

  - Can't wait very long.  This implies using multiple threads.

  - Not practical to compute md5s

  - known usage patterns mean we can simply use modification times.

- Addresses an insane requirement of emulating insane rewrites by
  making extra data copies. Whimper.

Basic architecture
==================

On each syncronization:

- Get {path->mtime} mapping for s3 and for local file system.

  This is done in 2 threads.

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

0.5.0 (2013-09-26)
==================

- Implement simple prefix rewrites that duplicate keys matching certain
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
