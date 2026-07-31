# Maintainer: tails1154
pkgname=blocksmith-launcher
pkgver=2.1.0
pkgrel=1
pkgdesc='Minecraft Java launcher powered by PortableMC and Modrinth'
arch=('x86_64')
url='https://github.com/tails1154/Blocksmith-Launcher'
license=('LicenseRef-Proprietary')
depends=('glibc' 'tk')
makedepends=('python' 'python-platformdirs')
options=('!debug')
source=(
  "$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz"
  'portablemc-4.4.1.whl::https://files.pythonhosted.org/packages/68/92/3ffda059f75068caf1de17c78c29d3a0746835d598e82abf77180092d124/portablemc-4.4.1-py3-none-any.whl'
)
sha256sums=(
  'fbcbe100e8b751f23f24e1541d7649dc70d9319a407930f670aa20183695a00d'
  '82435214f4745fb0b5a6dbbb065b1b22723f5805d2468a74c896b33733eb2de6'
)

prepare() {
  rm -rf vendor
  mkdir vendor
  bsdtar -xf portablemc-4.4.1.whl -C vendor
  pip install pyinstaller --break-system-packages
}

build() {
  cd "Blocksmith-Launcher-$pkgver"
  PYTHONPATH="$srcdir/vendor" python -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "$srcdir/dist" \
    --workpath "$srcdir/build" \
    Blocksmith.spec
}

package() {
  cd "Blocksmith-Launcher-$pkgver"
  install -Dm755 "$srcdir/dist/Blocksmith" "$pkgdir/usr/bin/Blocksmith"
  ln -s Blocksmith "$pkgdir/usr/bin/blocksmith"
  install -Dm644 packaging/blocksmith.desktop \
    "$pkgdir/usr/share/applications/blocksmith.desktop"
  install -Dm644 assets/blocksmith-256.png \
    "$pkgdir/usr/share/icons/hicolor/256x256/apps/blocksmith.png"
  install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
}
