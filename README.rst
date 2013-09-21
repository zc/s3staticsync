Yet another took for syncing files to S3
****************************************

Why? It was easier to write the tool I needed than to figure out
if existing tools did what I needed (sad, I know).

This tool is specifically designed for syncing static web sites
managed via FTP to S3.

- Posix (don't need windows support)

- Efficient:

  - Need to work with millions of files (but not 10s of millions)

  - Can't wait very long.  This implies using multiple threads.

  - Not practical to compute md5s

  - known usage patterns mean we can simply use modification times.

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

Changes
*******

0.1.0 (yyyy-mm-dd)
==================

Initial release
