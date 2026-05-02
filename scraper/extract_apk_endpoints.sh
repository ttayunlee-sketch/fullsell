#!/bin/bash
# Скачивает свежий APK UZUM Market и извлекает все URL endpoints.
# Нужно: curl, unzip, strings (binutils)
#
# Запуск: bash extract_apk_endpoints.sh

set -e

WORKDIR=/tmp/uzum_apk
APK_URL="${UZUM_APK_URL:-https://d.apkpure.net/b/APK/uz.uzum.market?version=latest}"

echo "═══════════════════════════════════════════════════"
echo "  📱 UZUM APK — извлечение API endpoints"
echo "═══════════════════════════════════════════════════"
echo ""

# 0. Зависимости
for tool in curl unzip strings; do
  if ! command -v $tool &>/dev/null; then
    echo "📦 Устанавливаю $tool..."
    sudo apt install -y -q $(echo "$tool" | sed 's/strings/binutils/')
  fi
done

mkdir -p "$WORKDIR"
cd "$WORKDIR"

# 1. Скачиваем APK
if [ ! -f uzum.apk ]; then
  echo "📥 Скачиваю APK..."
  echo "   URL: $APK_URL"
  curl -fsSL -A "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36" -o uzum.apk "$APK_URL" || {
    echo "❌ Не удалось скачать с APKPure (часто требует ручного клика)."
    echo ""
    echo "⚠️  Скачай APK руками с одного из сайтов:"
    echo "   https://m.apkpure.com/uzum-market/uz.uzum.market"
    echo "   https://apkcombo.com/uzum-market/uz.uzum.market/"
    echo "   https://uzum-market.en.aptoide.com/app"
    echo ""
    echo "После скачивания — положи файл сюда:"
    echo "   scp uzum.apk ttayunlee@138.249.248.45:$WORKDIR/uzum.apk"
    exit 1
  }
fi

echo "📊 Размер APK: $(du -h uzum.apk | cut -f1)"

# 2. Распаковываем
if [ ! -d unpacked ]; then
  echo "📂 Распаковываю..."
  mkdir -p unpacked
  unzip -q uzum.apk -d unpacked/
fi

# 3. Извлекаем URLs из всех classes*.dex
echo ""
echo "🔍 Ищу URLs в classes.dex..."
echo ""

ALL_URLS=$(strings unpacked/classes*.dex 2>/dev/null | \
  grep -oE 'https?://[a-zA-Z0-9.-]+(/[a-zA-Z0-9./_?=-]*)?' | \
  sort -u)

# 4. Группируем по интересам
echo "═══════════════ uzum.uz ═══════════════"
echo "$ALL_URLS" | grep -E 'uzum\.uz' | head -40

echo ""
echo "═══════════════ api / mobile / v1 / v2 ═══════════════"
echo "$ALL_URLS" | grep -iE '(api\.|m\.|mobile|v[0-9]/|graphql|/cabinet/)' | grep -E 'uzum' | head -30

echo ""
echo "═══════════════ Все домены (top-level) ═══════════════"
echo "$ALL_URLS" | grep -oE '://[a-zA-Z0-9.-]+' | sort -u | head -30

echo ""
echo "═══════════════ Полный список URLs (первые 100) ═══════════════"
echo "$ALL_URLS" | head -100

# 5. Сохраняем для анализа
echo "$ALL_URLS" > all_urls.txt
echo ""
echo "💾 Все URLs сохранены: $WORKDIR/all_urls.txt ($(wc -l < all_urls.txt) строк)"
