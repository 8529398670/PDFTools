#!/usr/bin/env bash
# Build qpdf as WebAssembly into static/vendor/qpdf/ (qpdf.js + qpdf.wasm), for
# the actions that run in the browser (static/js/local/). The same qpdf the
# server uses through pikepdf, so a split made here matches one made there.
#
# Needs Emscripten (emcc, emcmake, embuilder), cmake, ninja and curl. The build
# happens in a temporary folder; only the two output files land in the repo.
#
# Usage: scripts/build_qpdf_wasm.sh [qpdf-version]
#
# What the flags are for:
# - zlib and libjpeg come from Emscripten's own ports. pkg-config is switched
#   off so the host's libraries are never picked up by mistake.
# - native crypto: qpdf's built-in, so no OpenSSL to port.
# - -fwasm-exceptions: qpdf throws often; native wasm exceptions are much faster
#   than the JS-emulated ones (every current browser has them).
# - MAXIMUM_MEMORY=4GB with growth: the most wasm32 can address. It is qpdf's
#   working memory, not a cap on file size: the source is read lazily through
#   WORKERFS, slice by slice, never copied in whole.
# - INVOKE_RUN=0 / EXIT_RUNTIME=0: the page calls qpdf's main once per step,
#   many times over, on one loaded module.
# - ENVIRONMENT=worker,node: a Web Worker in the page; node for
#   scripts/check_local_split.py (through scripts/local_split.js), which
#   tests this very file against the server's split.
set -euo pipefail

VERSION="${1:-12.3.2}"
ROOT="$( cd "$( dirname "$0" )/.." && pwd )"
OUT="${ROOT}/static/vendor/qpdf"

for tool in emcc emcmake embuilder cmake ninja curl; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: $tool is not on PATH." >&2; exit 1; }
done

WORK="$( mktemp -d )"
trap 'rm -rf "$WORK"' EXIT
cd "$WORK"

echo "Downloading qpdf ${VERSION}..."
curl -fsSL -o qpdf.tar.gz "https://github.com/qpdf/qpdf/releases/download/v${VERSION}/qpdf-${VERSION}.tar.gz"
tar xzf qpdf.tar.gz

echo "Building zlib and libjpeg for Emscripten..."
embuilder build zlib libjpeg >/dev/null

LINK="-O2 -fwasm-exceptions -sUSE_ZLIB=1 -sUSE_LIBJPEG=1 \
  -sMODULARIZE=1 -sEXPORT_NAME=createQpdf -sENVIRONMENT=worker,node \
  -sALLOW_MEMORY_GROWTH=1 -sMAXIMUM_MEMORY=4GB -sSTACK_SIZE=1MB \
  -sINVOKE_RUN=0 -sEXIT_RUNTIME=0 -sFORCE_FILESYSTEM=1 \
  -sEXPORTED_RUNTIME_METHODS=callMain,FS -lworkerfs.js -lnodefs.js"

echo "Configuring..."
PKG_CONFIG_PATH= PKG_CONFIG_LIBDIR=/nonexistent emcmake cmake -S "qpdf-${VERSION}" -B build -G Ninja \
  -DCMAKE_DISABLE_FIND_PACKAGE_PkgConfig=ON \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DBUILD_STATIC_LIBS=ON -DBUILD_DOC=OFF \
  -DUSE_IMPLICIT_CRYPTO=OFF -DREQUIRE_CRYPTO_NATIVE=ON -DINSTALL_EXAMPLES=OFF \
  -DCMAKE_C_FLAGS="-O2 -fwasm-exceptions" -DCMAKE_CXX_FLAGS="-O2 -fwasm-exceptions" \
  -DCMAKE_EXE_LINKER_FLAGS="$LINK" >/dev/null

echo "Compiling (a few minutes)..."
ninja -C build qpdf/qpdf.js >/dev/null

mkdir -p "$OUT"
cp build/qpdf/qpdf.js build/qpdf/qpdf.wasm "$OUT/"
echo "$VERSION" > "$OUT/VERSION"
echo "Done: $( du -h "$OUT/qpdf.wasm" | cut -f1 ) in ${OUT#"$ROOT"/}/"
