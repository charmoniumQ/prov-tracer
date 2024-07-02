use std::{io::Write, path::Path};

use color_eyre::eyre::{Result, WrapErr};

use crate::util::Dir;

pub fn transcribe<P: AsRef<Path>, T: Write>(
    record_dir: P,
    tar: &mut tar::Builder<T>,
) -> Result<()> {
    let log_dir = Dir::temp(true).wrap_err("Failed to create temp directory for transcription")?;

    probe_frontend::transcribe::parse_top_level(record_dir, &log_dir)
        .wrap_err("Failed to transcribe record directory")?;

    tar.append_dir_all(".", &log_dir)
        .wrap_err("Failed to copy output dir into archive")?;
    tar.finish().wrap_err("Failed to finish writing tarball")?;

    Ok(())
}
