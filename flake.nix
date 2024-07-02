{
  inputs.flake-utils.url = "github:numtide/flake-utils";

  outputs = {
    self,
    nixpkgs,
    flake-utils,
  }:
    flake-utils.lib.eachDefaultSystem (
      system: let
        pkgs = nixpkgs.legacyPackages.${system};
        python312-debug = pkgs.python312.overrideAttrs (oldAttrs: {
          configureFlags = oldAttrs.configureFlags ++ ["--with-pydebug"];
          # patches = oldAttrs.patches ++ [ ./python.patch ];
        });
        export-and-rename = pkg: file-pairs: pkgs.stdenv.mkDerivation {
          pname = "${pkg.pname}-only-bin";
          dontUnpack = true;
          version = pkg.version;
          buildInputs = [ pkg ];
          buildPhase = builtins.concatStringsSep
            "\n"
            (builtins.map
              (pairs: "install -D ${pkg}/${builtins.elemAt pairs 0} $out/${builtins.elemAt pairs 1}")
              file-pairs);
        };
      in {
        packages = {
          python-dbg = python312-debug;
        };
        devShells = {
          default = pkgs.mkShell {
            buildInputs = [
              (pkgs.python312.withPackages (pypkgs: [
                pypkgs.typer
                pypkgs.pycparser
                pypkgs.pytest
                pypkgs.mypy
                pypkgs.pygraphviz
                pypkgs.networkx
                pypkgs.ipython
                pypkgs.pydot                
              ]))
              # (export-and-rename python312-debug [["bin/python" "bin/python-dbg"]])
              pkgs.gcc
              pkgs.gdb
              pkgs.coreutils
              pkgs.bash
              pkgs.xdot
              pkgs.alejandra
            ];
          };
        };
      }
    );
}