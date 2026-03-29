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
        pythonPkgs = python.pkgs;

        pythonEnv = python.withPackages (ps: with ps; [
          streamlit
          pandas
          plotly
        ]);
      in
      {
        packages.default = pkgs.writeShellScriptBin "hypodetektiv" ''
          cd ${self}
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
