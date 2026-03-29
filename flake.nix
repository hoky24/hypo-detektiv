{
  description = "HypoDetektiv — srovnání hypoték při refinancování";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python3;

        pythonEnv = python.withPackages (ps: with ps; [
          streamlit
          pandas
          plotly
        ]);

        appSrc = pkgs.lib.cleanSource self;
      in
      {
        packages.default = pkgs.writeShellScriptBin "hypodetektiv" ''
          WORKDIR=$(mktemp -d)
          cp -r ${appSrc}/*.py ${appSrc}/data "$WORKDIR/" 2>/dev/null || true
          cd "$WORKDIR"
          trap "rm -rf $WORKDIR" EXIT
          ${pythonEnv}/bin/streamlit run app.py --server.headless true "$@"
        '';

        apps.default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/hypodetektiv";
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [
            pythonEnv
          ];
          shellHook = ''
            echo "HypoDetektiv — vývojové prostředí"
            echo "Spuštění: streamlit run app.py"
          '';
        };
      }
    );
}
