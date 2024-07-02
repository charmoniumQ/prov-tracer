use std::{
    fs::File,
    io::{Read, Write},
    path::Path,
};

use chrono::{DateTime, SecondsFormat};
use color_eyre::eyre::{eyre, Result, WrapErr};
use probe_frontend::ops;
use serde::{Deserialize, Serialize};

/// Print the ops from a probe log out for humans.
///
/// This hides some of the data and so is not suitable for machine consumption use
/// [`to_stdout_json()`] instead.
pub fn to_stdout<P: AsRef<Path>>(tar_path: P) -> Result<()> {
    dump_internal(tar_path, |(pid, epoch, tid), ops| {
        let mut stdout = std::io::stdout().lock();
        for op in ops {
            writeln!(stdout, "{}.{}.{} >>> {}", pid, epoch, tid, op.dump())?;
        }
        Ok(())
    })
}

/// Prints the ops from a probe log out for machine consumption.
///
/// The ops are emitted one on each line, in the form:
///
/// ```
/// { "pid": X, "exec_epoch": Y, "tid": Z, "op": {...} }
/// ```
///
/// (without whitespace)
pub fn to_stdout_json<P: AsRef<Path>>(tar_path: P) -> Result<()> {
    dump_internal(tar_path, |(pid, epoch, tid), ops| {
        let mut stdout = std::io::stdout().lock();

        for op in ops {
            let json = serde_json::to_string(&DumpOp {
                pid,
                exec_epoch: epoch,
                tid,
                op,
            })?;
            writeln!(stdout, "{}", json)?;
        }
        Ok(())
    })
}

fn dump_internal<P: AsRef<Path>, F: Fn((usize, usize, usize), Vec<ops::Op>) -> Result<()>>(
    tar_path: P,
    printer: F,
) -> Result<()> {
    let file = flate2::read::GzDecoder::new(File::open(&tar_path).wrap_err_with(|| {
        eyre!(format!(
            "Failed to open input file '{}'",
            tar_path.as_ref().to_string_lossy()
        ))
    })?);

    let mut tar = tar::Archive::new(file);

    tar.entries()
        .wrap_err("Unable to get tarball entry iterator")?
        .try_for_each(|x| {
            let mut entry = x.wrap_err("Unable to extract tarball entry")?;

            let path = entry
                .path()
                .wrap_err("Error getting path of tarball entry")?
                .as_ref()
                // this forced UTF-8 conversion is permitted because these paths are strictly
                // within the tarball *we wrote*, so the paths should be all ASCII
                .to_str()
                .ok_or_else(|| eyre!("Tarball entry path not valid UTF-8"))?
                .to_owned();

            // if path == "_metadata" {
            //     return Ok(());
            // }

            let mut buf = String::new();
            let size = entry
                .read_to_string(&mut buf)
                .wrap_err("unable to read contents of tarball entry")?;

            // this is the case where the entry is a directory
            if size == 0 {
                return Ok(());
            }

            let hierarchy = path
                .split('/')
                .map(|x| {
                    x.parse::<usize>()
                        .wrap_err(format!("Unable to convert path component '{x}' to integer"))
                })
                .collect::<Result<Vec<_>, _>>()
                .wrap_err("Unable to extract PID.EPOCH.TID hierarchy")?;

            if hierarchy.len() != 3 {
                return Err(eyre!("malformed PID.EPOCH.TID hierarchy"));
            }
            let op_id_triple = (hierarchy[0], hierarchy[1], hierarchy[2]);

            let ops = buf
                .split('\n')
                .filter_map(|x| {
                    if x.is_empty() {
                        return None;
                    }
                    Some(serde_json::from_str::<ops::Op>(x).wrap_err("Error deserializing Op"))
                })
                .collect::<Result<Vec<_>, _>>()
                .wrap_err("Failed to deserialize TID file")?;

            printer(op_id_triple, ops)?;

            Ok(())
        })
}

/// Helper struct constructed from pid/epoch/tid hierarchy information and an op. Used for
/// serialization.
#[derive(Debug, Clone, Serialize, Deserialize)]
struct DumpOp {
    pid: usize,
    exec_epoch: usize,
    tid: usize,
    op: ops::Op,
}

// TODO: Display won't work (foreign trait rule) but some kind of streaming would be better; if we
// don't care about UTF-8 guarantees we might be able to do some kind of byte iterator approach and
// evaluate it all lazily
trait Dump {
    fn dump(&self) -> String;
}

impl Dump for ops::statx_timestamp {
    fn dump(&self) -> String {
        match DateTime::from_timestamp(self.tv_sec, self.tv_nsec) {
            Some(x) => x.to_rfc3339_opts(SecondsFormat::Secs, true),
            None => "[INVALID TIMESTAMP]".to_owned(),
        }
    }
}

impl Dump for ops::timeval {
    fn dump(&self) -> String {
        match DateTime::from_timestamp(self.tv_sec, self.tv_usec as u32 * 1000) {
            Some(x) => x.to_rfc3339_opts(SecondsFormat::Secs, true),
            None => "[INVALID TIMESTAMP]".to_owned(),
        }
    }
}

impl Dump for ops::statx {
    fn dump(&self) -> String {
        format!(
            "[ uid={}, gid={}, mode={:#06o} ino={}, size={}, mtime={} ]",
            self.stx_uid,
            self.stx_gid,
            self.stx_mode,
            self.stx_ino,
            self.stx_size,
            self.stx_mtime.dump(),
        )
    }
}

impl Dump for ops::rusage {
    fn dump(&self) -> String {
        format!(
            "[ utime={}, stime={}, maxrss={} ]",
            self.ru_utime.dump(),
            self.ru_stime.dump(),
            self.ru_maxrss,
        )
    }
}

impl Dump for ops::Path {
    fn dump(&self) -> String {
        format!(
            "[ dirfd={}, path='{}', inode={}, mtime={} ]",
            self.dirfd_minus_at_fdcwd + libc::AT_FDCWD,
            self.path.to_string_lossy(),
            self.inode,
            self.mtime.dump(),
        )
    }
}

impl Dump for ops::CloneOp {
    fn dump(&self) -> String {
        format!(
            "[ child_process_id={}, child_thread_id={}, errno={} ]",
            self.child_process_id, self.child_thread_id, self.ferrno,
        )
    }
}

impl Dump for ops::CloseOp {
    fn dump(&self) -> String {
        format!(
            "[ low_fd={}, high_fd={}, errno={} ]",
            self.low_fd, self.high_fd, self.ferrno,
        )
    }
}

impl Dump for ops::ExitOp {
    fn dump(&self) -> String {
        format!(
            "[ satus={}, run_atexit_handlers={} ]",
            self.status, self.run_atexit_handlers,
        )
    }
}

impl Dump for ops::GetRUsageOp {
    fn dump(&self) -> String {
        format!(
            "[ waitpid_arg={}, getrusage_arg={}, usage={}, errno={} ]",
            self.waitpid_arg,
            self.getrusage_arg,
            self.usage.dump(),
            self.ferrno,
        )
    }
}

impl Dump for ops::InitProcessOp {
    fn dump(&self) -> String {
        format!("[ pid={} ]", self.pid)
    }
}

impl Dump for ops::InitThreadOp {
    fn dump(&self) -> String {
        format!("[ tid={} ]", self.tid)
    }
}

impl Dump for ops::WaitOp {
    fn dump(&self) -> String {
        format!(
            "[ pid={}, options={}, status={}, ret={}, errno={} ]",
            self.pid, self.options, self.status, self.ret, self.ferrno,
        )
    }
}

impl Dump for ops::InitExecEpochOp {
    fn dump(&self) -> String {
        format!(
            "[ epoch={}, program_name={} ]",
            self.epoch,
            self.program_name.to_string_lossy(),
        )
    }
}

impl Dump for ops::OpenOp {
    fn dump(&self) -> String {
        format!(
            "[ path={}, flags={}, mode={:#06o} fd={}, errno={} ]",
            self.path.dump(),
            self.flags,
            self.mode,
            self.fd,
            self.ferrno,
        )
    }
}

impl Dump for ops::ChdirOp {
    fn dump(&self) -> String {
        format!("[ path={}, errno={} ]", self.path.dump(), self.ferrno,)
    }
}

impl Dump for ops::ExecOp {
    fn dump(&self) -> String {
        format!("[ path={}, errno={} ]", self.path.dump(), self.ferrno,)
    }
}

impl Dump for ops::AccessOp {
    fn dump(&self) -> String {
        format!(
            "[ path={}, mode={:#06o}, flags={}, errno={} ]",
            self.path.dump(),
            self.mode,
            self.flags,
            self.ferrno,
        )
    }
}

impl Dump for ops::StatOp {
    fn dump(&self) -> String {
        format!(
            "[ path={}, flags={}, statx_buf={}, errno={} ]",
            self.path.dump(),
            self.flags,
            self.statx_buf.dump(),
            self.ferrno,
        )
    }
}

impl Dump for ops::ReaddirOp {
    fn dump(&self) -> String {
        format!(
            "[ dir={}, child='{}', all_children={}, errno={} ]",
            self.dir.dump(),
            self.child.to_string_lossy(),
            self.all_children,
            self.ferrno,
        )
    }
}

impl Dump for ops::Metadata {
    fn dump(&self) -> String {
        match self {
            ops::Metadata::Mode { mode } => format!("Mode[ mode={:#06o} ]", mode),
            ops::Metadata::Ownership { uid, gid } => {
                format!("Ownership[ uid={}, gid={} ]", uid, gid)
            }
            ops::Metadata::Times {
                is_null,
                atime,
                mtime,
            } => format!(
                "Times[ is_null={}, atime={}, mtime={} ]",
                is_null,
                atime.dump(),
                mtime.dump()
            ),
        }
    }
}

impl Dump for ops::UpdateMetadataOp {
    fn dump(&self) -> String {
        format!(
            "[ path={}, flags={}, metadata={}, errno={} ]",
            self.path.dump(),
            self.flags,
            self.metadata.dump(),
            self.ferrno,
        )
    }
}

impl Dump for ops::ReadLinkOp {
    fn dump(&self) -> String {
        format!(
            "[ path={}, resolved='{}', errno={} ]",
            self.path.dump(),
            self.resolved.to_string_lossy(),
            self.ferrno
        )
    }
}

impl Dump for ops::OpInternal {
    fn dump(&self) -> String {
        fn wfmt(x: &str, y: &impl Dump) -> String {
            format!("{}{}", x, y.dump())
        }

        match self {
            ops::OpInternal::InitProcessOp(x) => wfmt("InitProcessOp", x),
            ops::OpInternal::InitExecEpochOp(x) => wfmt("InitExecEpochOp", x),
            ops::OpInternal::InitThreadOp(x) => wfmt("InitThreadOp", x),
            ops::OpInternal::OpenOp(x) => wfmt("OpenOp", x),
            ops::OpInternal::CloseOp(x) => wfmt("CloseOp", x),
            ops::OpInternal::ChdirOp(x) => wfmt("ChdirOp", x),
            ops::OpInternal::ExecOp(x) => wfmt("ExecOp", x),
            ops::OpInternal::CloneOp(x) => wfmt("CloneOp", x),
            ops::OpInternal::ExitOp(x) => wfmt("ExitOp", x),
            ops::OpInternal::AccessOp(x) => wfmt("AccessOp", x),
            ops::OpInternal::StatOp(x) => wfmt("StatOp", x),
            ops::OpInternal::ReaddirOp(x) => wfmt("ReadirOp", x),
            ops::OpInternal::WaitOp(x) => wfmt("WaitOp", x),
            ops::OpInternal::GetRUsageOp(x) => wfmt("GetRUsageOp", x),
            ops::OpInternal::UpdateMetadataOp(x) => wfmt("UpdateMetadataOp", x),
            ops::OpInternal::ReadLinkOp(x) => wfmt("ReadLinkOp", x),
        }
    }
}

impl Dump for ops::Op {
    fn dump(&self) -> String {
        self.data.dump()
    }
}
