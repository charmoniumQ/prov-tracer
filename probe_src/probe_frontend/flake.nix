{
  description = "libprobe frontend";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

    crane = {
      url = "github:ipetkov/crane";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    flake-utils.url = "github:numtide/flake-utils";

    advisory-db = {
      url = "github:rustsec/advisory-db";
      flake = false;
    };
  };

  # TODO: cleanup derivations and make more usable:
  # - version of probe cli with bundled libprobe and wrapper script
  # - python code as actual module
  # (this may require merging this flake with the top-level one)
  outputs = {
    self,
    nixpkgs,
    crane,
    flake-utils,
    advisory-db,
    ...
  }:
    flake-utils.lib.eachDefaultSystem (system: let
      pkgs = nixpkgs.legacyPackages.${system};
      # inherit (pkgs) lib;

      craneLib = crane.mkLib pkgs;
      src = ./.;

      # Common arguments can be set here to avoid repeating them later
      commonArgs = {
        inherit src;
        strictDeps = true;

        # all the crates in this workspace either use rust-bindgen or depend
        # on local crate that does.
        nativeBuildInputs = [
          pkgs.rustPlatform.bindgenHook
        ];
      };

      # Build *just* the cargo dependencies (of the entire workspace),
      # so we can reuse all of that work (e.g. via cachix) when running in CI
      # It is *highly* recommended to use something like cargo-hakari to avoid
      # cache misses when building individual top-level-crates
      cargoArtifacts = craneLib.buildDepsOnly commonArgs;

      individualCrateArgs =
        commonArgs
        // {
          inherit cargoArtifacts;
          inherit (craneLib.crateNameFromCargoToml {inherit src;}) version;
          # NB: we disable tests since we'll run them all via cargo-nextest
          doCheck = false;
        };

      # Build the top-level crates of the workspace as individual derivations.
      # This allows consumers to only depend on (and build) only what they need.
      # Though it is possible to build the entire workspace as a single derivation,
      # so this is left up to you on how to organize things
      probe-frontend = craneLib.buildPackage (individualCrateArgs
        // {
          pname = "probe-frontend";
          cargoExtraArgs = "-p probe_frontend";
        });
      probe-cli = craneLib.buildPackage (individualCrateArgs
        // {
          pname = "probe-cli";
          cargoExtraArgs = "-p probe_cli";
        });
      probe-macros = craneLib.buildPackage (individualCrateArgs
        // {
          pname = "probe-macros";
          cargoExtraArgs = "-p probe_macros";
          installPhase = ''
            mkdir -p $out
            cp -r python $out/python
          '';
        });
    in {
      checks = {
        # Build the crates as part of `nix flake check` for convenience
        inherit probe-frontend probe-cli probe-macros;

        # Run clippy (and deny all warnings) on the workspace source,
        # again, reusing the dependency artifacts from above.
        #
        # Note that this is done as a separate derivation so that
        # we can block the CI if there are issues here, but not
        # prevent downstream consumers from building our crate by itself.
        probe-workspace-clippy = craneLib.cargoClippy (commonArgs
          // {
            inherit cargoArtifacts;
            cargoClippyExtraArgs = "--all-targets -- --deny warnings";
          });

        probe-workspace-doc = craneLib.cargoDoc (commonArgs
          // {
            inherit cargoArtifacts;
          });

        # Check formatting
        probe-workspace-fmt = craneLib.cargoFmt {
          inherit src;
        };

        # Audit dependencies
        probe-workspace-audit = craneLib.cargoAudit {
          inherit src advisory-db;
        };

        # Audit licenses
        probe-workspace-deny = craneLib.cargoDeny {
          inherit src;
        };

        # Run tests with cargo-nextest
        # this is why `doCheck = false` on other crate derivations, to not run
        # the tests twice.
        probe-workspace-nextest = craneLib.cargoNextest (commonArgs
          // {
            inherit cargoArtifacts;
            partitions = 1;
            partitionType = "count";
          });

        probe-pygen-sanity = pkgs.runCommand "pygen-sanity-check" {} ''
          cp ${probe-macros}/python/ops.py $out
          ${pkgs.python312}/bin/python $out
        '';
      };

      packages = {
        inherit probe-cli probe-frontend probe-macros;
      };

      devShells.default = craneLib.devShell {
        # Inherit inputs from checks.
        checks = self.checks.${system};

        shellHook = ''
          export __PROBE_LIB=$(realpath ../libprobe/build)
        '';

        packages = [
          pkgs.cargo-audit
          pkgs.cargo-expand
          pkgs.cargo-flamegraph
          pkgs.cargo-watch
          pkgs.rust-analyzer
        ];
      };
    });
}
