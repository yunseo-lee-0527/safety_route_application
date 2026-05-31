import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# 한글 폰트
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

df = pd.read_csv("taas_accidents_with_latlon.csv", encoding="utf-8-sig")
df = df.dropna(subset=["lon", "lat"])

fig, ax = plt.subplots(figsize=(8, 8))
ax.scatter(df["lon"], df["lat"], s=20, c="red", alpha=0.6, linewidths=0)
ax.set_xlabel("경도 (lon)")
ax.set_ylabel("위도 (lat)")
ax.set_title(f"교통사고 위치 ({len(df)}건)")
ax.set_aspect("equal")
plt.tight_layout()
plt.show()
