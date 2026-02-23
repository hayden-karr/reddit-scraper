{
  description = "Reddit Scraper - Nix devenv";

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
            nasm # Required for rav1e assembly

            # Build dependencies for Python extensions and Rust
            pkg-config
            cmake
            ninja
            gcc
            openssl
            openssl.dev

            # Dioxus desktop (WebKitGTK) dependencies
            glib
            gtk3
            webkitgtk_4_1
            libsoup_3
            atk
            cairo
            gdk-pixbuf
            pango
            harfbuzz
            xdotool

            # Development headers
            libavif.dev
            libaom.dev

            # FFmpeg with full codec support
            ffmpeg-full

            # Tools
            git
          ];

          shellHook = ''
            echo "Reddit Scraper Dev Shell"
          '';
        };

        # Docker image
        packages.docker = pkgs.dockerTools.buildImage {
          name = "reddit-scraper";
          tag = "latest";

          copyToRoot = pkgs.buildEnv {
            name = "image-root";
            paths = with pkgs; [
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
            pathsToLink = [ "/bin" ];
          };

          config = {
            Env = [
              "LD_LIBRARY_PATH=${pkgs.libavif}/lib:${pkgs.libaom}/lib:${pkgs.dav1d}/lib:${pkgs.rav1e}/lib"
            ];
            WorkingDir = "/app";
            Cmd = [ "${pkgs.python313}/bin/python" "-m" "reddit_scraper.cli" ];
          };
        };
      });
}
