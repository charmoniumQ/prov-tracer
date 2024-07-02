
# PROBE Frontend

Tools for recording and manipulating libprobe provenance.

## Terminology

The documentation in this project assumes the reader understands a couple pieces
of terminology specific to this tool.

- **Probe record** (or probe recording)  
This is a directory (`probe_record` by default) that contains raw arena
allocator `*.dat` files created by libprobe, these files contain
[mmap(2)](https://www.man7.org/linux/man-pages/man2/mmap.2.html)-ed c structures
and are not guaranteed to valid if moved to a computer with a different
architecture, kernel version, or c compiler (or if any of those things change on
the same computer).

- **Probe log**  
This is a directory or file (`probe_log` by default) that encodes the data
from a probe record in a format that is cross-platform and much easier to use.
(see the section on serialization format for details).

- **Transcription**  
This is the process of converting a probe record to a probe log.

- **Translation**  
This is the process of polypeptide synthesis from mRNA strands generated during
[**transcription**](https://en.wikipedia.org/wiki/Transcription_(biology)).
(joke)

## Using the CLI to create probe logs

the simplest invocation of the `probe` cli is

```bash
probe record <CMD>
```

this will run `<CMD>` under the benevolent supervision of libprobe, outputting
the probe record to a temporary directory. Upon the process exiting, `probe` it
will transcribe the record directory and write a probe log file named `probe_log` in
the current directory.

If you run this again you'll notice it throws an error that the output file
already exists, solve this by passing `-o <PATH>` to specify a new file to write
the log to, or by passing `-f` to overwrite the previous log.

The transcription process can take a while after the program exits, if you don't
want to automatically transcribe the record, you can pass the `-n` flag, this
will change the default output path from `probe_log` to `probe_record`, and will
output a probe record directory that can be transcribed to a probe log later
with the `probe transcribe` command.

### Subshells

`probe record` does **not** pass your command through a shell, any
subshell or environment substitutions will still be performed by your shell
before the arguments are passed to `probe`. But it won't understand flow control
statements like `if` and `for`, shell builtins like `cd`, or shell
aliases/functions.

If you need these you can either write a shell script and
invoke `probe record` on that, or else run:

```bash
probe record -- bash -c '<SHELL_CODE>'`
```

(note the `--` so that `probe` doesn't try to parse `-c` as a flag).

## Serialization formats

### Probe record directory

The format of the probe record directory is defined by libprobe and not part of
this tool's spec, however a best-effort explanation is still given.

- Each probe record directory is composed of a top-level directory containing
one or more PID directories.

- Each PID directory has a numeric name corresponding to the PID of the process
who's provenance is recorded inside it, and in turn contains one or more exec
epoch directories.

- Each exec epoch directory has a numeric name corresponding to the exec epoch
of the virtual memory space who's provenance is recorded inside it, and in turn
contains one or more TID directories.

- Each TID directory has a numeric name corresponding to the TID of the thread
who's provenance is recorded inside it, it contains two subdirectories named
`data` and `ops`

- The `data` and `ops` directories both contains one or more files of the form
`X.dat` where `X` is a number, the `.dat` files inside the `data` directory are
called "data arenas", while those in the `ops` directory are called "op arenas".

- Each op arena is a binary file containing an arena header followed by zero or
more op c structs, followed by zero or more null bytes.

- Each data arena is a binary file containing an arena header followed by zero
or more bytes of arbitrary data, followed by zero or more null bytes.

### Probe log directory

This format **is** part of this tool's spec, and this tool is the source of
truth for its format.

- The format of the top-level, PID, and exec epoch directories is the same as
for the probe record directory described above, but rather than containing TID
directories, each exec epoch directory contains one or more TID files.

- Each TID file has a numeric name corresponding to the TID of the thread who's
provenance is recorded inside it. It is a [jsonlines](https://jsonlines.org/)
file, where each line is an op (as defined in this library) serialized as json.

### Probe log file

This format is simply a probe log directory that's bundled into a tar archive
and compressed with gzip, since its easier to move as a single file and
compresses well.
