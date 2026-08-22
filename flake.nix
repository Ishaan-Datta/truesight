{
  description = "Truesight";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      uv2nix,
      pyproject-nix,
      pyproject-build-systems,
      ...
    }:
    let
      overlay = final: prev: {
        truesight = final.callPackage ./nix/package.nix {
          inherit uv2nix pyproject-nix pyproject-build-systems;
        };
      };
    in
    {
      overlays.default = overlay;
    }
    // flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = [ overlay ];
        };
      in
      {
        packages.default = pkgs.truesight;
        packages.truesight = pkgs.truesight;

        apps.default = {
          type = "app";
          program = "${pkgs.truesight}/bin/truesight";
          meta.description = "Capture a screenshot and extract its text with Surya OCR";
        };
        apps.truesight = self.apps.${system}.default;

        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.python312
            pkgs.ruff
            pkgs.uv
            pkgs.niri
            pkgs.wl-clipboard
            pkgs.libnotify
          ];

          shellHook = ''
            export UV_PYTHON="${pkgs.python312}/bin/python"
            export UV_PYTHON_DOWNLOADS=never
            unset PYTHONPATH
            uv sync
          '';
        };
      }
    );
}
