# Transferring a project

In an open Windows project, expand **Export project archive**, enter an archive
name and list the supporting files you have permission to transfer. Use project-relative
paths such as `documents/supplement.pdf` and `exports/Reviewed.xlsx`.
Include every locally linked document. Confirm permission for the database
and selected files and choose a destination folder. Existing files are preserved.

On the receiving computer, open **Import project archive**, optionally enter a
new folder name, then choose the archive and its destination parent folder. The
app opens the restored working project. It retains its original UUID, search
history, publication decisions and jobs. You can keep the archive as a backup.
The format provides integrity checks. Anyone with access to the archive can
read its contents.

The version 1 archive contains a compacted SQLite backup, the project manifest,
an inventory of SHA-256 checksums and the selected supporting files. SQLite
captures committed data while another connection is open. Machine credential
settings, diagnostics and backups are outside the transfer inventory. The
database may contain retained abstracts and private researcher notes.

Restoration checks the inventory, the current project schema, database integrity
and linked document paths in private staging. The verified directory is
published in one operation. An existing destination is preserved. A hard
interruption can leave a private staging directory in the selected parent.
Run archive creation or restoration again with the same source to recover.
The format supports up to 16,384 payload files, 4 GiB per file and 8 GiB in total.
