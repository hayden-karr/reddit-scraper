{
  description = "Reddit Scraper - Nix shell with AVIF support";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let pkgs = nixpkgs.legacyPackages.${system};
      in {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            # Python and uv
            python313
            uv

            # Rust toolchain for media engine
            rustc
            cargo
            rustfmt
            clippy

            # AVIF system libraries
            libavif
            libaom
            dav1d
            rav1e
            nasm # Required for rav1e assembly optimizations

            # Build dependencies for Python extensions
            pkg-config
            cmake
            ninja
            gcc

            # Development headers (sometimes needed)
            libavif.dev
            libaom.dev

            # FFmpeg with full codec support
            ffmpeg-full

            # Other useful tools
            git
          ];

          # Comprehensive environment setup
          shellHook = ''
            # Library paths for both build and runtime
            export PKG_CONFIG_PATH="${pkgs.libavif}/lib/pkgconfig:${pkgs.libaom}/lib/pkgconfig:${pkgs.dav1d}/lib/pkgconfig:${pkgs.rav1e}/lib/pkgconfig:$PKG_CONFIG_PATH"
            export LD_LIBRARY_PATH="${pkgs.libavif}/lib:${pkgs.libaom}/lib:${pkgs.dav1d}/lib:${pkgs.rav1e}/lib:$LD_LIBRARY_PATH"
            export LIBRARY_PATH="${pkgs.libavif}/lib:${pkgs.libaom}/lib:${pkgs.dav1d}/lib:${pkgs.rav1e}/lib:$LIBRARY_PATH"

            # Header paths for compilation
            export CPATH="${pkgs.libavif}/include:${pkgs.libaom}/include:${pkgs.dav1d}/include:$CPATH"
            export C_INCLUDE_PATH="$CPATH"
            export CPLUS_INCLUDE_PATH="$CPATH"

            # Ensure pip/uv can find system libraries when building extensions
            export CMAKE_PREFIX_PATH="${pkgs.libavif}:${pkgs.libaom}:${pkgs.dav1d}:${pkgs.rav1e}:$CMAKE_PREFIX_PATH"

            echo "Reddit Scraper Dev Shell"
            echo "System AVIF libraries:"
            echo "FFmpeg AVIF support: $(ffmpeg -hide_banner -encoders 2>/dev/null | grep -i avif | wc -l) encoders"
            echo ""
            echo "Setup commands:"
            echo "1. uv venv"
            echo "2. source .venv/bin/activate"
            echo "3. uv pip install --force-reinstall --no-binary=pillow-avif-plugin pillow pillow-avif-plugin"
            echo "4. python -c 'import pillow_avif; print(\"AVIF OK\")'"
          '';
        };

        # Docker image with proper AVIF support
        packages.docker = pkgs.dockerTools.buildImage {
          name = "reddit-scraper";
          tag = "latest";

          contents = with pkgs; [
            python313
            libavif
            libaom
            dav1d
            rav1e
            ffmpeg-full
            bash
            coreutils
            findutils
          ];

          config = {
            Env = [
              "PKG_CONFIG_PATH=${pkgs.libavif}/lib/pkgconfig:${pkgs.libaom}/lib/pkgconfig"
              "LD_LIBRARY_PATH=${pkgs.libavif}/lib:${pkgs.libaom}/lib:${pkgs.dav1d}/lib:${pkgs.rav1e}/lib"
              "LIBRARY_PATH=${pkgs.libavif}/lib:${pkgs.libaom}/lib:${pkgs.dav1d}/lib:${pkgs.rav1e}/lib"
            ];
            WorkingDir = "/app";
            Cmd = [ "${pkgs.python313}/bin/python" "-m" "reddit_scraper.cli" ];
          };
        };
      });
}
