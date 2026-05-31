# 의왕시 보행안전지수 산출 방법론 (참고)

관악구 도로 위험도 지수의 방법론 기반. 의왕시 전체 도로링크 994개에 적용된 원형 방법론이다.

---

## 지표 체계

| 카테고리 | 변수 |
|---|---|
| 환경 | 도로시설물, 도로 폭(차로 수) |
| 보행자 | 도로·요일별 보행자 수, 보행약자 유동인구 |
| 운전자 | 통행량, 통행속도 |

변수 선정은 보행사고와의 상관관계 분석으로 수행한다.

---

## 변수 선정

### 링크별 사고 수 산출

```python
road_acc = {i: 0 for i in road}
for x in range(len(acc)):
    for i in range(1, 4):
        try:
            road_acc[acc[f'LINK_ID_{i}'][x]] += 1
        except:
            pass
```

### 상관관계 분석을 통한 변수 선정

```python
corr_road_mean = sum(np.abs(corr_var_road_df)) / len(np.abs(corr_var_road_df))

mask_1 = (corr_var_road_df > corr_road_mean)
mask_2 = (corr_var_road_df < (corr_road_mean * -1))

selected_corr_road_var_df = pd.concat([
    corr_var_road_df.loc[mask_1],
    corr_var_road_df.loc[mask_2]
])
```

---

## 가중치 산출식

$$w = 1 + \frac{r_i}{\sum r}$$

| 기호 | 의미 |
|---|---|
| `w` | 가중치 |
| `r_i` | 보행사고와 해당 변수의 상관계수 |
| `r` | 보행사고와 각 변수의 상관계수 전체 |

### 통행량 가중치 (6차로 이상 + 평균속도 ≥ 제한속도)

```python
acc_road_six = abs(
    corr_weight_road_df.iloc[-1, :-1].loc['LINK_SUM_TAXI_제곱근 변환']
) / np.sum(corr_weight_road_list)
acc_road_six = round(acc_road_six, 3) + 1

df_merge_final['6차로 가중치'] = df_merge_final.apply(
    lambda df: (1.0 if df['LINK_SUM_TAXI'] == 0 else acc_road_six),
    axis=1
)
```

### 보행약자 가중치

어린이·노인·장애인 유동인구 비율이 평균 초과인 도로, 또는 반경 300m 내 해당 시설물이 있는 도로에 곱셈 가중치 적용.

```python
df_merge_final['보행약자(유동인구) 가중치'] = df_merge_final.apply(
    lambda df: (
        (1.0 if df['어린이유동인구 평균'] <= kid_weight_mean else acc_person_kid) *
        (1.0 if df['노인유동인구 평균']   <= old_weight_mean else acc_person_old) *
        (1.0 if df['장애인유동인구 평균'] <= hand_weight_mean else acc_person_hand)
    ),
    axis=1
)

df_merge_final['최종 가중치'] = (
    df_merge_final['보행약자(유동인구) 가중치'] *
    df_merge_final['보행약자(시설물) 가중치'] *
    df_merge_final['6차로 가중치']
)
```

---

## 보행안전지수 산출

```python
from sklearn.preprocessing import StandardScaler

stScaler = StandardScaler()
df_merge_final[selected_columns] = stScaler.fit_transform(df_merge_final[selected_columns])

# 보행안전지수 = Σ(구성변수 z-score) × 최종 가중치
df_merge_final['보행안전지수'] = df_merge_final.apply(
    lambda df: sum(df[selected_columns]) * df['최종 가중치'],
    axis=1
)
```

---

## 전체 파이프라인

```text
[원천 데이터: 환경/보행자/운전자]
        │
        ▼
[데이터 검증·전처리]
        │
        ▼
[변수 후보군 구축: 링크별 사고 수, 시설물 수]
        │
        ▼
[상관관계 분석 → 최종 변수 선정]
        │
        ▼
[가중치 산출: 통행량(대로) × 보행약자 유동인구 × 보행약자 시설물]
        │
        ▼
[StandardScaler 표준화]
        │
        ▼
[보행안전지수 = Σ(z-score) × 최종 가중치]
        │
        ▼
[QGIS 시각화: 10단계 분류]
```
