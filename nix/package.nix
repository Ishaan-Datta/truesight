{
  lib,
  stdenvNoCC,
  callPackage,
  makeWrapper,
  python312,
  niri,
  wl-clipboard,
  libnotify,
  uv2nix,
  pyproject-nix,
  pyproject-build-systems,
}:

let
  workspace = uv2nix.lib.workspace.loadWorkspace {
    workspaceRoot = ./..;
  };

  pythonSet = (callPackage pyproject-nix.build.packages { python = python312; }).overrideScope (
    lib.composeManyExtensions [
      pyproject-build-systems.overlays.default
      (workspace.mkPyprojectOverlay {
        sourcePreference = "wheel";
      })
    ]
  );

  project = pythonSet.truesight;
  pythonEnv = pythonSet.mkVirtualEnv "${project.pname}-env" workspace.deps.default;
in
stdenvNoCC.mkDerivation {
  pname = project.pname;
  version = project.version;
  src = ./..;

  nativeBuildInputs = [ makeWrapper ];
  buildInputs = [ pythonEnv ];

  dontBuild = true;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/bin
    makeWrapper ${pythonEnv}/bin/truesight $out/bin/truesight \
      --prefix PATH : ${lib.makeBinPath [
        niri
        wl-clipboard
        libnotify
      ]}

    runHook postInstall
  '';

  doCheck = true;
  checkPhase = ''
    runHook preCheck
    ${pythonEnv}/bin/python -m unittest discover
    runHook postCheck
  '';

  meta = {
    description = "Capture screenshots and extract their text with Surya OCR";
    platforms = lib.platforms.linux;
    mainProgram = "truesight";
  };
}
