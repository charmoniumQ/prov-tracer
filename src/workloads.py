import charmonium.time_block as ch_tb
import shutil
import hashlib
import subprocess
import re
import urllib.parse
from collections.abc import Sequence, Mapping
from pathlib import Path
from util import run_all, CmdArg, check_returncode, merge_env_vars
import yaml
from typing import cast

# ruff: noqa: E501

result_bin = (Path(__file__).parent / "result").resolve() / "bin"
result_lib = result_bin.parent / "lib"


class Workload:
    kind: str
    name: str

    def setup(self, workdir: Path) -> None:
        pass

    def run(self, workdir: Path) -> tuple[Sequence[CmdArg], Mapping[CmdArg, CmdArg]]:
        return ["true"], {"PATH": str(result_bin)}

    def __str__(self) -> str:
        return self.name


class SpackInstall(Workload):
    kind = "compilation"

    def __init__(self, specs: list[str], version: str = "v0.20.1") -> None:
        self.name = "compile " + "+".join(specs)
        self._version = version
        self._env_dir: Path | None = None
        self._specs = specs
        self._env_vars: Mapping[str, str] = {}

    def setup(self, workdir: Path) -> None:
        self._env_vars = {
            "PATH": str(result_bin),
            "SPACK_USER_CACHE_PATH": str(workdir),
            "SPACK_USER_CONFIG_PATH": str(workdir),
            "LD_LIBRARY_PATH": str(result_lib),
            "LIBRARY_PATH": str(result_lib),
            "SPACK_PYTHON": f"{result_bin}/python",
        }

        # Install spack
        spack_dir = workdir / "spack"
        if not spack_dir.exists():
            check_returncode(subprocess.run(
                run_all(
                    (
                        f"{result_bin}/git", "clone", "-c", "feature.manyFiles=true",
                        "https://github.com/spack/spack.git", str(spack_dir),
                    ),
                    (
                        f"{result_bin}/git", "-C", str(spack_dir), "checkout",
                        self._version, "--force",
                    ),
                ),
                env=self._env_vars,
                check=False,
                capture_output=True,
            ), env=self._env_vars)
        spack = spack_dir / "bin" / "spack"
        assert spack.exists()
        spack.write_text(spack.read_text().replace("#!/bin/sh", f"#!{result_bin}/sh"))

        # Concretize env with desired specs
        env_name = urllib.parse.quote("-".join(self._specs), safe="")
        if len(env_name) > 64:
            env_name = hashlib.sha256(env_name.encode()).hexdigest()[:16]
        env_dir = workdir / "spack_envs" / env_name
        if not env_dir.exists():
            env_dir.mkdir(parents=True)
            check_returncode(subprocess.run(
                [spack, "env", "create", "--dir", env_dir],
                env=self._env_vars,
                check=False,
                capture_output=True,
            ), env=self._env_vars)
        conf_obj = yaml.safe_load((env_dir / "spack.yaml").read_text())
        if True:
            compiler = conf_obj.setdefault("spack", {}).setdefault("compilers", [{}])[0].setdefault("compiler", {})
            compiler.setdefault("environment", {}).setdefault("prepend_path", {})["LIBRARY_PATH"] = str(result_lib)
            compiler.setdefault("paths", {})["cc"] = str(result_bin / "gcc")
            compiler.setdefault("paths", {})["cxx"] = str(result_bin / "g++")
            compiler.setdefault("paths", {})["f77"] = None
            compiler.setdefault("paths", {})["fc"] = None
            compiler["modules"] = []
            compiler["operating_system"] = "ubuntu22.04"
            compiler["spec"] = "gcc@=12.3.0"
            (env_dir / "spack.yaml").write_text(yaml.dump(conf_obj))
        exports = check_returncode(subprocess.run(
            [spack, "env", "activate", "--sh", "--dir", env_dir],
            env=self._env_vars,
            check=False,
            text=True,
            capture_output=True,
        ), env=self._env_vars).stdout
        pattern = re.compile('^export ([a-zA-Z0-9_]+)="?(.*?)"?;?$', flags=re.MULTILINE)
        self._env_vars = cast(Mapping[str, str], merge_env_vars(
            self._env_vars,
            {
                match.group(1): match.group(2)
                for match in pattern.finditer(exports)
            },
        ))
        check_returncode(subprocess.run(
            [spack, "add", *self._specs],
            env=self._env_vars,
            check=False,
            capture_output=True,
        ), env=self._env_vars)
        spec_shorthand = ", ".join(spec.partition("@")[0] for spec in self._specs)
        if not (env_dir / "spack.lock").exists():
            with ch_tb.ctx(f"concretize {spec_shorthand}"):
                check_returncode(subprocess.run(
                    [spack, "concretize"],
                    env=self._env_vars,
                    check=False,
                    capture_output=True,
                ), env=self._env_vars)
        with \
             (env_dir / "spack_install_stdout").open("wb") as stdout, \
             (env_dir / "spack_install_stderr").open("wb") as stderr, \
             ch_tb.ctx(f"install {spec_shorthand}"):
            print(f"`tail --follow {env_dir}/spack_install_stdout` to check progress. Same applies to stderr")
            check_returncode(subprocess.run(
                [spack, "install"],
                env=self._env_vars,
                check=False,
                stdout=stdout,
                stderr=stderr,
            ), env=self._env_vars)

        # Find deps of that env and take out specs we asked for
        with ch_tb.ctx("get deps"):
            script = "; ".join([
                "import spack.environment",
                f"env = spack.environment.Environment('{env_dir}')",
                "print('\\n'.join(map(str, set(env.all_specs()))))",
            ])
            dependency_specs = list(filter(bool, check_returncode(subprocess.run(
                (spack, "python", "-c", script),
                env=self._env_vars,
                check=False,
                capture_output=True,
                text=True,
            ), env=self._env_vars).stdout.strip().split("\n")))

            generalized_specs = [
                spec.partition("@")[0]
                for spec in self._specs
            ]
            [
                spec
                for spec in dependency_specs
                if spec.partition("@")[0] in generalized_specs
            ]
            [
                spec
                for spec in dependency_specs
                if spec.partition("@")[0] not in generalized_specs
            ]

        # Create mirror with source code of self._specs
        name = "env_mirror"
        mirror_dir = env_dir / name
        mirrors = check_returncode(subprocess.run(
            (spack, "mirror", "list"),
            env=self._env_vars,
            check=False,
            capture_output=True,
            text=True,
        ), env=self._env_vars).stdout
        if name not in mirrors:
            with ch_tb.ctx(f"create mirror {name}"):
                if mirror_dir.exists():
                    shutil.rmtree(mirror_dir)
                mirror_dir.mkdir()
                check_returncode(subprocess.run(
                    (spack, "mirror", "create", "--directory", mirror_dir, "--all"),
                    env=self._env_vars,
                    check=False,
                    capture_output=True,
                ))
                rel_mirror_dir = mirror_dir.resolve().relative_to(env_dir)
                check_returncode(subprocess.run(
                    (spack, "mirror", "add", name, rel_mirror_dir),
                    env=self._env_vars,
                    check=False,
                    capture_output=True,
                ), env=self._env_vars)

        # Ensure target specs are uninstalled
        with ch_tb.ctx("Uninstalling specs"):
            for spec in generalized_specs:
                has_spec = subprocess.run(
                    [
                        spack, "find", spec,
                    ],
                    env=self._env_vars,
                    check=False,
                    capture_output=True,
                ).returncode == 0
                if has_spec:
                    check_returncode(subprocess.run(
                        [
                            spack, "uninstall", "--all", "--yes", "--force", *spec,
                        ],
                        check=False,
                        capture_output=True,
                        env=self._env_vars,
                    ), env=self._env_vars)

    def run(self, workdir: Path) -> tuple[Sequence[CmdArg], Mapping[CmdArg, CmdArg]]:
        spack = workdir / "spack/bin/spack"
        assert self._env_dir
        assert "LD_PRELOAD" not in self._env_vars
        assert "LD_LIBRARY_PATH" not in self._env_vars
        assert "HOME" not in self._env_vars
        # env=patchelf%400.13.1%3A0.13%20%25gcc%20target%3Dx86_64-openblas
        # env - PATH=$PWD/result/bin HOME=$HOME $(jq  --join-output --raw-output 'to_entries[] | .key + "=" + .value + " "' .workdir/work/spack_envs/$env/env_vars.json) .workdir/work/spack/bin/spack --debug bootstrap status 2>~/Downloads/stderr_good.txt >~/Downloads/stdout_good.txt
        # sed -i $'s/\033\[[0-9;]*m//g' ~/Downloads/stderr*.txt
        # sed -i 's/==> \[[0-9:. -]*\] //g' ~/Downloads/stderr*.txt
        return (
            (spack, "--debug", "install"),
            {k: v for k, v in self._env_vars.items()},
        )


class KaggleNotebook(Workload):
    kind = "data science"

    def __init__(
            self,
            kernel: str,
            competition: str,
            replace: Sequence[tuple[str, str]],
    ) -> None:
        # kaggle kernels pull pmarcelino/comprehensive-data-exploration-with-python
        # kaggle competitions download -c house-prices-advanced-regression-techniques
        self._kernel = kernel
        self._competition = competition
        self._replace = replace
        self._notebook: None | Path = None
        self._data_zip: None | Path = None
        author, name = self._kernel.split("/")
        self.name = author + "-" + name[:4]

    def setup(self, workdir: Path) -> None:
        self._notebook = workdir / "kernel" / (self._kernel.split("/")[1] + ".ipynb")
        self._data_zip = workdir / (self._competition.split("/")[1] + ".zip")
        if not self._notebook.exists():
            check_returncode(subprocess.run(
                [
                    result_bin / "kaggle", "kernels", "pull", "--path",
                    workdir / "kernel", self._kernel
                ],
                env={"PATH": str(result_bin)},
                check=False,
                capture_output=True,
            ))
            notebook_text = self._notebook.read_text()
            for bad, good in self._replace:
                notebook_text = notebook_text.replace(bad, good)
            self._notebook.write_text(notebook_text)
        if not self._data_zip.exists():
            check_returncode(subprocess.run(
                [
                    result_bin / "kaggle", "competitions", "download", "--path",
                    workdir, self._competition.split("/")[1]
                ],
                check=False,
                capture_output=True,
            ))
        if (workdir / "input").exists():
            shutil.rmtree(workdir / "input")
        check_returncode(subprocess.run(
            [result_bin / "unzip", "-o", "-d", workdir / "input", self._data_zip],
            env={"PATH": str(result_bin)},
            check=False,
            capture_output=True,
        ))

    def run(self, workdir: Path) -> tuple[Sequence[CmdArg], Mapping[CmdArg, CmdArg]]:
        assert self._notebook
        return (
            (
                (result_bin / "python").resolve(), "-m", "jupyter", "nbconvert", "--execute",
                "--to=markdown", self._notebook,
            ),
            {
                "PATH": str(result_bin),
            },
        )


class Cmds(Workload):
    def __init__(self, kind: str, name: str, setup: tuple[CmdArg, ...], run: tuple[CmdArg, ...]) -> None:
        self.kind = kind
        self.name = name
        self._setup = setup
        self._run = run

    def _replace_args(self, args: tuple[CmdArg, ...], workdir: Path) -> tuple[CmdArg, ...]:
        return tuple(
            (
                arg.replace("$WORKDIR", str(workdir))
                if isinstance(arg, str) else
                arg.replace(b"$WORKDIR", str(workdir).encode())
                if isinstance(arg, bytes) else
                arg
            )
            for arg in args
        )

    def setup(self, workdir: Path) -> None:
        check_returncode(subprocess.run(
            self._replace_args(self._setup, workdir),
            env={"PATH": str(result_bin)},
            check=False,
            capture_output=True,
        ))

    def run(self, workdir: Path) -> tuple[tuple[CmdArg, ...], Mapping[CmdArg, CmdArg]]:
        return tuple(self._replace_args(self._run, workdir)), {}

apache_ver = "httpd-2.4.58"

def genomics_workload(name: str, which_targets: tuple[str, ...]) -> Cmds:
    return Cmds(
        "genomics",
        name,
        (
            result_bin / "sh",
            "-c",
            f"""
                if [ ! -d $WORKDIR/blast-benchmark ]; then
                    {result_bin}/curl --output-dir $WORKDIR --remote-name https://ftp.ncbi.nih.gov/blast/demo/benchmark/benchmark2013.tar.gz
                    mkdir --parents $WORKDIR/blast-benchmark
                    {result_bin}/tar --extract --file $WORKDIR/benchmark2013.tar.gz --directory $WORKDIR/blast-benchmark --strip-components 1
                fi
                {result_bin}/rm --recursive --force $WORKDIR/blast-benchmark/output
                {result_bin}/mkdir $WORKDIR/blast-benchmark/output
                {result_bin}/env --chdir=$WORKDIR/blast-benchmark/output {result_bin}/mkdir blastn blastp blastx tblastn tblastx megablast idx_megablast
            """,
        ),
        (
            result_bin / "make",
            "--directory=$WORKDIR/blast-benchmark",
            f"BLASTN={result_bin}/blastn",
            f"BLASTP={result_bin}/blastp",
            f"BLASTX={result_bin}/blastx",
            f"TBLASTN={result_bin}/tblastn",
            f"TBLASTP={result_bin}/tblastp",
            f"MEGABLAST={result_bin}/blastn -task megablast -use_index false",
            f"IDX_MEGABLAST={result_bin}/blastn -task megablast -use_index true",
            f"IDX_MEGABLAST={result_bin}/blastn -task megablast -use_index true",
            f"MAKEMBINDEX={result_bin}/makembindex -iformat blastdb -old_style_index false",
            "TIME=",
            *which_targets,
        ),
    )

WORKLOADS: Sequence[Workload] = (
    # Cmds("simple", "python", (result_bin / "ls", "-l"), (result_bin / "python", "-c", "print(4)")),  # noqa: E501
    Cmds("simple", "python-imports", (result_bin / "ls", "-l"), (result_bin / "python", "-c", "import pandas, pymc, matplotlib")),
    # Cmds("simple", "gcc", (result_bin / "ls", "-l"), (result_bin / "gcc", "-Wall", "-Og", "test.c", "-o", "$WORKDIR/test.exe")),
    Cmds("simple", "gcc-math-pthread", (result_bin / "ls", "-l"), (result_bin / "gcc", "-DFULL", "-Wall", "-Og", "-pthread", "test.c", "-o", "$WORKDIR/test.exe", "-lpthread", "-lm")),
    Cmds(
        "compilation",
        "apache",
        (
            result_bin / "sh",
            "-c",
            f"""
                if [ ! -f $WORKDIR/httpd ]; then
                    {result_bin}/curl --output-dir $WORKDIR --remote-name https://dlcdn.apache.org/httpd/{apache_ver}.tar.bz2
                    {result_bin}/mkdir $WORKDIR/httpd
                    {result_bin}/tar --extract --file $WORKDIR/{apache_ver}.tar.bz2 --directory $WORKDIR/httpd --strip-components 1
                    {result_bin}/patch --directory=$WORKDIR/httpd --strip=1 < httpd-configure.patch
                    {result_bin}/sed --in-place s=/bin/sh={result_bin}/sh=g $WORKDIR/httpd/configure
                fi
            """,
        ),
        (
            result_bin / "sh",
            "-c",
            f"cd $WORKDIR/httpd && ./configure --with-pcre=$WORKDIR/pcre2-config && {result_bin}/make",
        )
    ),
    # SpackInstall(["patchelf@0.13.1:0.13 %gcc target=x86_64", "openblas"]),
    # SpackInstall(["hdf~mpi"]),
    # SpackInstall(["mpich"]),
    # SpackInstall(["mvapich2"]),
    # SpackInstall(["py-matplotlib"]),
    # SpackInstall(["gromacs"]),
    # SpackInstall(["perl"]),
    genomics_workload("blastx-10", ["NM_001004160", "NM_004838"]),
    genomics_workload("megablast-10", [
        "NM_001000841", "NM_001008511", "NM_007622", "NM_020327", "NM_032130",
        "NM_064997", "NM_071881", "NM_078614", "NM_105954", "NM_118167",
        "NM_127277", "NM_134656", "NM_146415", "NM_167127", "NM_180448"
    ]),
    genomics_workload("tblastn-10", ["NP_072902"]),
    KaggleNotebook(
        "pmarcelino/comprehensive-data-exploration-with-python",
        "competitions/house-prices-advanced-regression-techniques",
        replace=(
            (".corr()", ".corr(numeric_only=True)"),
            (
                "df_train['SalePrice'][:,np.newaxis]",
                "df_train['SalePrice'].values[:,np.newaxis]",
            ),
            (
                "df_train.drop((missing_data[missing_data['Total'] > 1]).index,1)",
                "df_train.drop((missing_data[missing_data['Total'] > 1]).index, axis=1)",
            ),
        ),
    ),
    KaggleNotebook(
        "startupsci/titanic-data-science-solutions",
        "competitions/titanic",
        replace=(
            (
                "sns.FacetGrid(train_df, col='Survived', row='Pclass', size=",
                "sns.FacetGrid(train_df, col='Survived', row='Pclass', height=",
            ),
            (
                "sns.FacetGrid(train_df, row='Embarked', size=",
                "sns.FacetGrid(train_df, row='Embarked', height=",
            ),
            (
                "sns.FacetGrid(train_df, row='Embarked', col='Survived', size=",
                "sns.FacetGrid(train_df, row='Embarked', col='Survived', height=",
            ),
            (
                "sns.FacetGrid(train_df, row='Pclass', col='Sex', size=",
                "sns.FacetGrid(train_df, row='Pclass', col='Sex', height=",
            )
        ),
    ),
    KaggleNotebook(
        "ldfreeman3/a-data-science-framework-to-achieve-99-accuracy",
        "competitions/titanic",
        replace=(
            (
                "from sklearn.preprocessing import Imputer , Normalizer",
                (
                    "from sklearn.impute import SimpleImputer as Imputer; "
                    "from sklearn.preprocessing import Normalizer"
                ),
            ),
            (
                "from pandas.tools.plotting import scatter_matrix",
                "from pandas.plotting import scatter_matrix",
            ),
            ("sns.factorplot(", "sns.catplot("),
            (".corr()", ".corr(numeric_only=True)"),
            (
                "data2.set_value(index, 'Random_Predict', 0)",
                "data2.loc[index, 'Random_Predict'] = 0",
            ),
            (
                "data2.set_value(index, 'Random_Predict', 1)",
                "data2.loc[index, 'Random_Predict'] = 1",
            ),
        ),
    ),
    KaggleNotebook(
        "yassineghouzam/titanic-top-4-with-ensemble-modeling",
        "competitions/titanic",
        replace=(
            ("sns.factorplot(", "sns.catplot("),
            (
                r'sns.kdeplot(train[\"Age\"][(train[\"Survived\"] == 0) & (train[\"Age\"].notnull())], color=\"Red\", shade',
                r'sns.kdeplot(train[\"Age\"][(train[\"Survived\"] == 0) & (train[\"Age\"].notnull())], color=\"Red\", fill',
            ),
            (
                r'sns.kdeplot(train[\"Age\"][(train[\"Survived\"] == 1) & (train[\"Age\"].notnull())], ax =g, color=\"Blue\", shade',
                r'sns.kdeplot(train[\"Age\"][(train[\"Survived\"] == 1) & (train[\"Age\"].notnull())], ax =g, color=\"Blue\", fill'
            ),
            ("dataset['Age'].iloc[i]", "dataset.loc[i, 'Age']"),
            ("sns.distplot", "sns.histplot"),
            (
                r'sns.catplot(x=\"SibSp\",y=\"Survived\",data=train,kind=\"bar\", size',
                r'sns.catplot(x=\"SibSp\",y=\"Survived\",data=train,kind=\"bar\", height',
            ),
            (
                r'sns.catplot(x=\"Parch\",y=\"Survived\",data=train,kind=\"bar\", size',
                r'sns.catplot(x=\"Parch\",y=\"Survived\",data=train,kind=\"bar\", height',
            ),
            (
                r'sns.catplot(x=\"Pclass\",y=\"Survived\",data=train,kind=\"bar\", size',
                r'sns.catplot(x=\"Pclass\",y=\"Survived\",data=train,kind=\"bar\", height',
            ),
            (
                r'sns.catplot(x=\"Pclass\", y=\"Survived\", hue=\"Sex\", data=train,\n                   size',
                r'sns.catplot(x=\"Pclass\", y=\"Survived\", hue=\"Sex\", data=train,\n                   height'),
            (
                r'sns.catplot(x=\"Embarked\", y=\"Survived\",  data=train,\n                   size',
                r'sns.catplot(x=\"Embarked\", y=\"Survived\",  data=train,\n                   height',
            ),
            (
                r'sns.catplot(\"Pclass\", col=\"Embarked\",  data=train,\n                   size',
                r'sns.catplot(x=\"Pclass\", col=\"Embarked\",  data=train,\n                   height',
            ),
            (
                r'set_xticklabels([\"Master\",\"Miss/Ms/Mme/Mlle/Mrs\",\"Mr\",\"Rare\"])',
                r'set_xticks(range(4), labels=[\"Master\",\"Miss/Ms/Mme/Mlle/Mrs\",\"Mr\",\"Rare\"])',
            ),
            (
                "sns.countplot(dataset[\\\"Cabin\\\"],order=['A','B','C','D','E','F','G','T','X'])",
                "sns.countplot(dataset, x='Cabin', order=['A','B','C','D','E','F','G','T','X'])",
            ),
            (
                "sns.barplot(\\\"CrossValMeans\\\",\\\"Algorithm\\\",data = cv_res, palette=\\\"Set3\\\",orient = \\\"h\\\",**{'xerr':cv_std})",
                "sns.barplot(x=\\\"CrossValMeans\\\",y=\\\"Algorithm\\\",data = cv_res, palette=\\\"Set3\\\",orient = \\\"h\\\",**{'xerr':cv_std})",
            ),
            (
                "train = dataset[:train_len]\ntest = dataset[train_len:]\n",
                "train = dataset[:train_len].copy()\ntest = dataset[train_len:].copy()\n",
            ),
            # (r'g.set_xlabel(\"Mean Accuracy\")', ""),
            # (r'g = g.set_title(\\"Cross validation scores\\")', ""),
            ('\'loss\' : [\\"deviance\\"]', '\'loss\' : [\\"log_loss\\"]'),
            ("n_jobs=4", "n_jobs=1"),
            ("n_jobs= 4", "n_jobs=1"),
            # Skip boring CPU-heavy computation
            (
                r'\"learning_rate\":  [0.0001, 0.001, 0.01, 0.1, 0.2, 0.3,1.5]',
                r'\"learning_rate\":  [0.3]',
            ),
            (
                r'\"min_samples_split\": [2, 3, 10]',
                r'\"min_samples_split\": [3]',
            ),
            (
                r'\"min_samples_leaf\": [1, 3, 10]',
                r'\"min_samples_leaf\": [3]',
            ),
            (
                r"'n_estimators' : [100,200,300]",
                r"'n_estimators' : [200]",
            ),
            (
                r"'C': [1, 10, 50, 100,200,300, 1000]",
                r"'C': [10]",
            ),
            (
                "kfold = StratifiedKFold(n_splits=10)",
                "kfold = StratifiedKFold(n_splits=3)",
            )
        ),
    ),
)
