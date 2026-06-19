# V3.1 Calibration Results

## Method

9 representative pairings × 2,000 Poisson-simulated matches each using the V3 Dynamic Team State Engine with:
- **Star-weighted positional averages** (CB 0.35×, ST 0.40×, FB 0.15×, etc.)
- **Non-linear strength curve** (`curve_factor=3.0`): `attack_ratio^3` amplifies rating gaps
- **National strength modifier** from V1 ELO/PELE (±3% max per team)
- **V3 dynamic state** (6-component multiplier clamped to 0.90–1.10)

### xG Formula

```
defensive_index = 0.70 × star_defense + 0.30 × star_goalkeeper
attack_ratio = star_attack / defensive_index
curve_value = attack_ratio^3           # non-linear amplification
midfield_modifier = 1.0 + 0.25 × (star_mid_att - star_mid_def) / 100
lambda = base_goals × curve_value × midfield_modifier
       × v3_dynamic_multiplier         # ±10% from form/chemistry/etc.
       × (1.0 + nat_mod_a - nat_mod_d)  # relative national strength
```

---

## Calibration Table

| Pair | Type | W% | D% | L% | Sim xG | Exp xG | Total G |
|---|---|---|---|---|---|---|---|
| France vs Switzerland | Elite vs Good | 58.5 | 25.1 | 16.4 | 1.67–0.76 | 1.71–0.76 | 2.43 |
| England vs Ghana | Elite vs Good | 61.4 | 19.9 | 18.8 | 2.03–1.01 | 2.01–0.99 | 3.04 |
| Brazil vs Japan | Good vs Decent | 56.9 | 22.9 | 20.3 | 1.77–0.99 | 1.77–0.96 | 2.76 |
| Germany vs Curaçao | Elite vs Weak | 69.1 | 20.4 | 10.5 | 1.89–0.56 | 1.88–0.53 | 2.45 |
| Argentina vs Jordan | Good vs Weak | 69.0 | 20.0 | 11.1 | 2.06–0.67 | 2.08–0.69 | 2.73 |
| Spain vs Mexico | Good vs Decent | 67.2 | 20.2 | 12.7 | 2.06–0.79 | 2.02–0.80 | 2.85 |
| Belgium vs Uruguay | Slight Favorite | 49.6 | 25.5 | 24.9 | 1.51–1.01 | 1.52–1.00 | 2.52 |
| Portugal vs Netherlands | Balanced | 40.6 | 24.6 | 34.8 | 1.35–1.22 | 1.38–1.16 | 2.57 |
| Senegal vs USA | Balanced | 44.0 | 23.2 | 32.9 | 1.46–1.22 | 1.46–1.22 | 2.68 |

---

## Key Findings

1. **Win probabilities are realistic**  
   - Elite vs Good: 58–61% favorite win (France/England)
   - Good vs Weak: 67–69% favorite win (Argentina/Spain vs weaker opponents)
   - Elite vs Weak: 69% (Germany vs Curaçao)
   - Balanced: 40–50% split (Portugal/Netherlands, Senegal/USA)

2. **Draw rates** (20–26%) match real-world World Cup average (~24%).

3. **Goal totals** (2.4–3.0 per match) are realistic for international football.

4. **Simulated vs Expected xG** align closely, confirming correct Poisson sampling.

5. **V3 dynamic range**: 0.975–1.100 (within ±10% limit).  
   **National modifier range**: –0.022 to +0.029 (within ±3% limit).

## Star-Weighted Rating Effect

| Team | Simple Avg Attack | Star-Wtd Attack | Diff |
|---|---|---|---|
| France | 88.2 | 88.6 | +0.31 |
| Brazil | 82.1 | 82.1 | +0.00 |
| Portugal | 82.4 | 82.0 | –0.32 |
| Ghana | 79.3 | 79.5 | +0.22 |
| Curaçao | 66.6 | 66.6 | +0.00 |

| Team | Simple Avg Defense | Star-Wtd Defense | Diff |
|---|---|---|---|
| Brazil | 74.1 | 77.0 | +2.85 |
| France | 82.5 | 84.1 | +1.52 |
| Portugal | 80.3 | 80.5 | +0.22 |
| Ghana | 72.1 | 73.4 | +1.31 |
| Curaçao | 70.4 | 70.4 | –0.06 |

Star weighting especially benefits teams with strong centre-backs (CB weight 0.35 vs FB 0.15) and star strikers (ST weight 0.40 vs WINGER 0.30).

## Config Parameters Used

| Parameter | Value | Source |
|---|---|---|
| `base_goals` | 1.10 | `calibration_config.json` |
| `curve_factor` | 3.0 | `calibration_config.json` |
| `attack_weight_defense` | 0.70 | `calibration_config.json` |
| `attack_weight_goalkeeper` | 0.30 | `calibration_config.json` |
| `midfield_control_weight` | 0.25 | `calibration_config.json` |
| `star_player_weights` | ST=0.40, WINGER=0.30, CM=0.35, DM=0.30, CB=0.35, FB=0.15, GK=1.00 | `calibration_config.json` |
| `v3_dynamic_multiplier` range | [0.90, 1.10] | `calibration_config.json` |
| National modifiers | –0.023 to +0.029 | `national_strength_modifiers.json` |
