#!/usr/bin/env bash
# Tạo lại các file Word trong thư mục này. Cần pandoc >= 3.0.
# Nguồn: src/*.md và ../context/04-quyet-dinh-da-chot.md. Kế hoạch A/B lấy từ ../ShipAudit_Ke-hoach-ky-thuat_AB.docx.
set -euo pipefail
export LANG=C.UTF-8 LC_ALL=C.UTF-8
cd "$(dirname "$0")"
REF=reference.docx
NGAY="Cập nhật $(date +%d/%m/%Y)"
HEAD="ShipAudit · MUGVN Hackathon 2026 · Real-time Operations (MongoDB × Datadog)"

pandoc src/ho-so-du-an.md --reference-doc="$REF" -M date="$NGAY" -o ShipAudit_01_Ho-so-du-an.docx
pandoc ../context/04-quyet-dinh-da-chot.md --shift-heading-level-by=-1 --reference-doc="$REF" \
  -M author="$HEAD" -M date="$NGAY" -o ShipAudit_02_Quyet-dinh-da-chot.docx
if [ -f ../ShipAudit_Ke-hoach-ky-thuat_AB.docx ]; then
  cp ../ShipAudit_Ke-hoach-ky-thuat_AB.docx ShipAudit_03_Ke-hoach-ky-thuat_AB.docx
fi
pandoc src/theo-doi-tien-do.md --reference-doc="$REF" -M date="$NGAY" -o ShipAudit_04_Theo-doi-tien-do.docx
pandoc src/brief-va-checklist.md --reference-doc="$REF" -M date="$NGAY" -o ShipAudit_05_Brief-va-checklist.docx
pandoc ../ban-giao-cho-A.md --reference-doc="$REF" -M date="$NGAY" -o ShipAudit_06_Ban-giao-cho-A.docx
echo "Xong. File Word nằm trong $(pwd)"
