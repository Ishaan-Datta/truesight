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
        # desktop-reminder-system = final.callPackage ./nix/package.nix {
        #   inherit uv2nix pyproject-nix pyproject-build-systems;
        # };
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
        # packages.default = pkgs.desktop-reminder-system;
        # packages.desktop-reminder-system = pkgs.desktop-reminder-system;

        # apps.default = {
        #   type = "app";
        #   program = "${pkgs.desktop-reminder-system}/bin/desktop-reminder-system";
        # };
        # apps.desktop-reminder-system = self.apps.${system}.default;

        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.python312
            pkgs.ruff
            pkgs.uv
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
