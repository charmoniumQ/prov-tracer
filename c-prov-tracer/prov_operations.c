enum OpCode {
    OpenRead,
    OpenReadWrite,
    OpenOverWrite,
    OpenWritePart,
    Execute,
    Close,
    Chdir,
    OpenDir,
    WalkDir,
    MetadataRead,
    MetadataWritePart,
    ReadLink,
};

struct Op {
    enum OpCode op_code;
    int dirfd;
    OWNED const char* path;
    int fd;
    struct InodeTriple inode_triple;
    mode_t mode;
};

static enum OpCode fopen_to_opcode(BORROWED const char* fopentype) {
    bool plus = fopentype[1] == '+' || (fopentype[1] != '\0' && fopentype[2] == '+');
    if (false) {
    } else if (fopentype[0] == 'r' && !plus) {
        return OpenRead;
    } else if (fopentype[0] == 'r' && plus) {
        return OpenReadWrite;
    } else if (fopentype[0] == 'w' && !plus) {
        return OpenOverWrite;
    } else if (fopentype[0] == 'w' && plus) {
        return OpenOverWrite;
    } else if (fopentype[0] == 'a' && !plus) {
        return OpenWritePart;
    } else if (fopentype[0] == 'a' && plus) {
        return OpenReadWrite;
    } else {
        fprintf(stderr, "Unknown fopentype %s\n", fopentype);
        abort();
    }
}

struct Op make_op(enum OpCode op_code, int dirfd, const char* OWNED path, int fd, mode_t mode) {
    struct Op op;
    op.op_code = op_code;
    op.dirfd = dirfd;
    op.fd = fd;
    op.mode = mode;
    if (path) {
        op.inode_triple = get_inode_triple(dirfd, path);
        /* This gets freed when the op gets logged in prov_log_save */
        EXPECT(, op.path = strndup(path, PATH_MAX));
    } else {
        op.inode_triple = null_inode_triple;
        op.path = path;
    }
    return op;
}

static BORROWED const char* op_code_to_string(enum OpCode op_code) {
    switch (op_code) {
        case OpenRead: return "OpenRead";
        case OpenReadWrite: return "OpenReadWrite";
        case OpenOverWrite: return "OpenOverWrite";
        case OpenWritePart: return "OpenWritePart";
        case Close: return "Close";
        case Chdir: return "Chdir";
        case OpenDir: return "OpenDir";
        case WalkDir: return "WalkDir";
        case MetadataRead: return "MetadataRead";
        case MetadataWritePart: return "MetadataWritePart";
        case ReadLink: return "ReadLink";
        case Execute: return "Execute";
        default:
            fprintf(stderr, "Unknown op_code %d (should be %d to %d)", op_code, OpenRead, ReadLink);
            abort();
    }
}

static void fprintf_op(BORROWED FILE* stream, struct Op op) {
    char null_byte = '\0';
    /*
     * Technically the path can have anything except null-byte, so I will have to use that to delimit the path
     * The op-code string, on the other hand, comes from an enum above, and can't contain werid chars.
     * The integers are likewise easy-to-parse.
     * */
    EXPECT(
        > 0,
        fprintf(
            stream,
            "%s %d %d %d %d %d %d %s%c\n",
            op_code_to_string(op.op_code),
            op.fd,
            op.dirfd,
            op.mode,
            op.inode_triple.inode,
            op.inode_triple.device_major,
            op.inode_triple.device_minor,
            op.path ? op.path : "",
            null_byte));
}

int null_fd = -20;
mode_t null_mode = -20;

enum OpCode open_flag_to_opcode(int flag) {
    if ((flag & O_ACCMODE) == O_RDWR) {
        if ((flag & O_CREAT) || (flag & O_TRUNC)) {
            return OpenOverWrite;
        } else {
            return OpenReadWrite;
        }
    } else if ((flag & O_ACCMODE) == O_RDONLY) {
        if ((flag & O_CREAT) || (flag & O_TRUNC)) {
            // Truncates the file, which is a write
            // And then reads from it. Maybe someone else wrote to it since then.
            return OpenReadWrite;
        } else {
            return OpenRead;
        }
    } else if ((flag & O_ACCMODE) == O_WRONLY) {
        if (flag & O_TMPFILE) {
            return OpenOverWrite;
        } else if ((flag & O_CREAT) || (flag & O_TRUNC)) {
            return OpenOverWrite;
        } else {
            return OpenWritePart;
        }
    } else if (flag & O_PATH) {
        // TODO: Note that opening with O_PATH can cause a file metadata read
        // int fd = open(path, O_PATH | O_DIRECTORY);
        // struct stat buf;
        // fstatat(fd, &buf);

        // TODO: Note that opening with O_PATH on a directory can cause a directory list
        // int fd = open(path, O_PATH | O_DIRECTORY);
        // DIR* dir = dirfd(fd);
        // readdir(dir);

        fprintf(stderr, "I don't really know what to do with this O_PATH\n");
        abort();
    } else {
        fprintf(stderr, "I don't really know what to do with this open mode %d %d %d %d\n", flag, O_RDWR, O_RDONLY, O_WRONLY);
        abort();
    }
}
