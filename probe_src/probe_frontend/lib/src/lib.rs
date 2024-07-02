/// transcribe probe record directories created by libprobe to log directories

/// Op definitions from `prov_ops.h`
///
/// This module contains ffi bindings for the raw C-structs emitted by libprobe, generated automatically with
/// rust-bindgen (these start with `C_`), as well as the converted version which can be serialized
///
/// While simple Ops containing only Integral values can be used/serialized directory from
/// libprobe, more complicated structs containing pointers (usually in the form of strings) need to
/// be manually converted to versions so they can be serialized. This module re-exports the trivial
/// structs and defines new ones (as well as methods for converting) for the non-trivial structs.
///
pub mod ops;

/// Convert part of all of a probe record directory to a probe log directory.
///
/// # Serialization format
///
/// The serialization format output is very similar to the raw libprobe arena format. It's a
/// filesystem hierarchy of `<PID>/<EXEC_EPOCH>/<TID>` but instead of `<TID>` being a directory containing
/// `ops` and `data` directories with the raw C-struct arenas, `<TID>` is a
/// [jsonlines](https://jsonlines.org/) file, where each line is a json representation of an
/// [`ops::Op`].
pub mod transcribe;

// currently unused, get system metadata
// mod metadata;

/// Library error type and definitions.
pub mod error;
