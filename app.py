from flask import Flask, request, jsonify
import numpy as np
import pandas as pd
import joblib
import json
import requests
import os
import google.generativeai as genai

app = Flask(__name__)

# ================= GEMINI CONFIG =================
GEMINI_API_KEY = "AIzaSyB8ZHTAxcJMzgQQrLRAxIF7uEAe0OKv99U"  # ✅ your key

genai.configure(api_key=GEMINI_API_KEY)

# ✅ FIXED MODEL NAME
gemini_model = genai.GenerativeModel("gemini-1.5-flash-latest")


# ================= AUTH0 CONFIG =================
AUTH0_DOMAIN = "dev-jgftvhmp83ujgcy2.us.auth0.com"

AUTH0_TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6IjZXbWR5cEU3cnhpcXVPLUVvVUhiNiJ9.eyJpc3MiOiJodHRwczovL2Rldi1qZ2Z0dmhtcDgzdWpnY3kyLnVzLmF1dGgwLmNvbS8iLCJzdWIiOiJYYmpSVnlSbHF2RVpHMmxIamdJcTJPTVVqZGFZQzMwd0BjbGllbnRzIiwiYXVkIjoiaHR0cHM6Ly9kZXYtamdmdHZobXA4M3VqZ2N5Mi51cy5hdXRoMC5jb20vYXBpL3YyLyIsImlhdCI6MTc3NTAzNTQwNiwiZXhwIjoxNzc1MTIxODA2LCJzY29wZSI6InJlYWQ6bG9ncyIsImd0eSI6ImNsaWVudC1jcmVkZW50aWFscyIsImF6cCI6IlhialJWeVJscXZFWkcybEhqZ0lxMk9NVWpkYVlDMzB3In0.i5VwiPcsaZZTLhkUl-QhIAOmqkvHFJVSKCXFMFJVVGLxkqDkK2lB6AeV92Bi19MWdnRAzfgUyLF_aO9Nmoh0mli5RZ7kbYLGtjM_kGkrnTtW83w68d7jFaL1LrL4U5Aa8tnm3bezktwNYzV7gzxx47TdXrVx4U_nYmyBb0kX3v3vu-v_4NicDQNtGVaKRU3h7M5DSkdG_sMUDe-RqNK5mvBW3DXmXI2_YVOHEJCIAUoFM9U4G0ZpVnUHQ7om4BlsbD2bO97BpY--XxmoRyR4wy4bOI2JWSlQLcBlJgxa8lnFmFxXKq59DGxwSSB80RNZDVQIxeUcrXxOWxfx5VMHOw"  # 🔥 paste FULL token here


# ================= LOAD MODEL =================
model = joblib.load("rf_model.pkl")
label_encoder = joblib.load("label_encoder.pkl")
explainer = joblib.load("explainer.pkl")

with open("features.json", "r") as f:
    feature_names = json.load(f)

# ---------------- ATTACK INFO ----------------
attack_description = {
    "BENIGN": "Normal network traffic.",
    "BOT": "Bot attack detected.",
    "DDOS ATTACK-HOIC": "DDoS flooding attack.",
    "DOS ATTACKS-HULK": "DoS Hulk attack.",
    "FTP-BRUTEFORCE": "FTP brute force attack.",
    "SSH-BRUTEFORCE": "SSH brute force attack."
}

attack_risk = {
    "BENIGN": "LOW",
    "BOT": "HIGH",
    "DDOS ATTACK-HOIC": "CRITICAL",
    "DOS ATTACKS-HULK": "CRITICAL",
    "FTP-BRUTEFORCE": "HIGH",
    "SSH-BRUTEFORCE": "HIGH"
}



# ---------------- SMART ATTACK DETECTION ----------------
def rule_based_detection(data):
    pkt_rate = data.get("Flow Pkts/s", 0)
    dst_port = data.get("Dst Port", 0)
    syn_flag = data.get("SYN Flag Cnt", 0)
    payload = data.get("Pkt Size Avg", 0)

    if pkt_rate > 5000:
        return "DDOS ATTACK-HOIC"

    if pkt_rate > 2000:
        return "DOS ATTACKS-HULK"

    if dst_port == 21 and syn_flag > 0:
        return "FTP-BRUTEFORCE"

    if dst_port == 22 and syn_flag > 0:
        return "SSH-BRUTEFORCE"

    if payload > 50:
        return "BOT"

    return None



# ================= AI EXPLANATION =================
def generate_ai_explanation(attack, risk, confidence):
    try:
        prompt = f"""
Explain this cyber attack:

Attack: {attack}
Risk: {risk}
Confidence: {confidence}%

Explain simply with:
- What it is
- Why it happens
- Impact
- Prevention
"""

        res = gemini_model.generate_content(prompt)
        return res.text

    except Exception as e:
        print("Gemini error:", e)
        return "AI explanation failed"


# ================= VPN CHECK =================
def check_vpn(ip):
    try:
        res = requests.get(f"http://ip-api.com/json/{ip}", timeout=3)
        data = res.json()
        return data.get("proxy", False)
    except:
        return False


# ================= ROUTES =================

@app.route("/")
def home():
    return jsonify({"message": "API Running"})


# ---------------- ROUTES ----------------
@app.route("/predict", methods=["POST"])
def predict():
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "No JSON input received"}), 400

        data = {k.strip(): v for k, v in data.items()}

        # RULE
        rule_attack = rule_based_detection(data)

        # FEATURES
        features = [data.get(f, 0) for f in feature_names]
        X = pd.DataFrame([features], columns=feature_names).astype(float)

        # ML
        prediction = int(model.predict(X)[0])
        ml_attack = label_encoder.inverse_transform([prediction])[0].upper()

        attack_type = rule_attack if rule_attack else ml_attack

        # CONFIDENCE
        probs = model.predict_proba(X)[0]
        confidence = round(np.max(probs) * 100, 2)

        if rule_attack:
            confidence = max(confidence, 90.0)

        # RISK
        risk_level = attack_risk.get(attack_type, "HIGH")

        # SHAP
        try:
            shap_values = explainer.shap_values(X)
            shap_array = np.array(shap_values).reshape(-1)

            if len(shap_array) < len(feature_names):
                shap_array = np.pad(
                    shap_array,
                    (0, len(feature_names) - len(shap_array)),
                    mode='constant'
                )
            else:
                shap_array = shap_array[:len(feature_names)]

        except Exception as e:
            print("SHAP error:", e)
            shap_array = np.zeros(len(feature_names))

        # TOP FEATURES
        top_indices = np.argsort(np.abs(shap_array))[-5:][::-1]

        explanation = []
        for i in top_indices:
            explanation.append({
                "feature": feature_names[i],
                "value": float(X.iloc[0, i]),
                "shap_impact": float(shap_array[i])
            })

        # 🔥 AI EXPLANATION
        ai_explanation = generate_ai_explanation(
            attack_type,
            risk_level,
            confidence
        )

        # RESPONSE
        return jsonify({
            "Attack_Type": attack_type,
            "Attack_Description": attack_description.get(attack_type, "Unknown attack"),
            "Trust_Score (%)": confidence,
            "Risk_Level": risk_level,
            "Explanation": explanation,
            "AI_Explanation": ai_explanation
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ================= LIVE LOGIN =================
@app.route("/live-logins")
def live_logins():
    try:
        url = f"https://{AUTH0_DOMAIN}/api/v2/logs"

        headers = {
            "Authorization": f"Bearer {AUTH0_TOKEN}"
        }

        params = {
            "q": 'type:"s"',   # successful login
            "sort": "date:-1",
            "per_page": 20
        }

        res = requests.get(url, headers=headers, params=params)

        if res.status_code != 200:
            return jsonify({
                "error": "Auth0 failed",
                "details": res.text
            }), 500

        logs = res.json()

        result = []

        for log in logs:
            ip = log.get("ip", "unknown")
            email = log.get("user_name", "unknown")
            time = log.get("date")

            vpn = check_vpn(ip)

            risk = "HIGH" if vpn else "LOW"

            result.append({
                "email": email,
                "ip": ip,
                "time": time,
                "vpn": vpn,
                "risk": risk
            })

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)