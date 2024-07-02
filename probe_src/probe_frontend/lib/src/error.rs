use std::num::ParseIntError;

pub type Result<T> = std::result::Result<T, ProbeError>;

#[non_exhaustive]
#[derive(Debug, thiserror::Error)]
pub enum ProbeError {
    /// wrapper explaining where an occurred converting a [`C_` struct](crate::ops) to its rust
    /// version, call [`root_cause()`](Self::root_cause()) to return the underlying error.
    #[error("{msg}: {inner}")]
    FFiConversionError {
        msg: &'static str,
        inner: Box<ProbeError>,
    },

    /// The tag of a tagged union type from an [`C_` struct](crate::ops) isn't a valid variant of
    /// that union
    #[error("Invalid variant of tagged union")]
    InvalidVariant(u32),

    /// A pointer from an [`C_` struct](crate::ops) couldn't be decoded into a byte slice.
    #[error("Unable to decode pointer {0:#x}")]
    InvalidPointer(usize),

    /// Unable to generate a [`CString`](std::ffi::CString) from a byte slice because it had no null byte.
    #[error("Expected null byte but none found")]
    MissingNull,

    /// Used instead of [`unreachable`] so that functions up the call stack can add
    /// [context](Self::Context).
    #[error("Reached code believed unreachable, please report this bug")]
    UnreachableCode,

    /// An error occurred serializing or deserializing a struct into/from json.
    #[error("(de)serialization error ({context}):\n{error}")]
    JsonError {
        context: &'static str,
        error: serde_json::Error,
    },

    /// A generic wrapper around another [`ProbeError`] type that adds additional context, call
    /// [`root_cause()`](Self::root_cause()) to return the underlying error.
    #[error("{context}:\n{error}")]
    Context {
        context: &'static str,
        error: Box<ProbeError>,
    },

    /// A wrapper over a [`std::io::Error`] with a description of what the was being done when an
    /// IO error occurred
    #[error("{context}:\n{error}")]
    ContextIO {
        context: &'static str,
        error: std::io::Error,
    },

    /// An external function returned [`None`] when [`Some`] was required, contains explanation.
    // FIXME: this is an unhelpful error
    #[error("{context}:\nNeeded Option was None")]
    MissingOption { context: &'static str },

    /// A wrapper over [`ArenaError`](crate::transcribe::ArenaError), see that type for variant
    /// details.
    #[error("{0}")]
    ArenaError(crate::transcribe::ArenaError),

    /// An error occured trying to parse a string into an integer, this error is generally wrapped
    /// in [context](Self::Context).
    #[error("{0}")]
    ParseIntError(ParseIntError),
}

impl ProbeError {
    /// Walks down the inner value(s) of one or more layers of [`Context`](Self::Context) or
    /// [`FfiConversionError`](Self::FFiConversionError) and returns a reference to the underlying
    /// error type, returns `&self` for other variants.
    pub fn root_cause(&self) -> &ProbeError {
        match self {
            Self::Context { error, .. } => error.as_ref().root_cause(),
            Self::FFiConversionError { inner, .. } => inner.as_ref().root_cause(),
            _ => self,
        }
    }
}

impl From<crate::transcribe::ArenaError> for ProbeError {
    fn from(value: crate::transcribe::ArenaError) -> Self {
        Self::ArenaError(value)
    }
}

impl From<ParseIntError> for ProbeError {
    fn from(value: ParseIntError) -> Self {
        Self::ParseIntError(value)
    }
}

/// create new [`ProbeError::MissingOption`] with the given context
pub(crate) fn option_err(context: &'static str) -> ProbeError {
    ProbeError::MissingOption { context }
}

pub(crate) trait WrapErr<T, E> {
    fn wrap_err(self, context: &'static str) -> Result<T>;
}

impl<T, E: ConvertErr> WrapErr<T, E> for std::result::Result<T, E> {
    fn wrap_err(self, context: &'static str) -> Result<T> {
        match self {
            Ok(x) => Ok(x),
            Err(e) => Err(e.convert(context)),
        }
    }
}

pub(crate) trait ConvertErr {
    fn convert(self, context: &'static str) -> ProbeError;
}

impl ConvertErr for std::io::Error {
    fn convert(self, context: &'static str) -> ProbeError {
        ProbeError::ContextIO {
            context,
            error: self,
        }
    }
}

impl ConvertErr for ProbeError {
    fn convert(self, context: &'static str) -> ProbeError {
        ProbeError::Context {
            context,
            error: Box::new(self),
        }
    }
}

impl ConvertErr for serde_json::Error {
    fn convert(self, context: &'static str) -> ProbeError {
        ProbeError::JsonError {
            context,
            error: self,
        }
    }
}
