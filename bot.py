import requests
from eth_account import Account
import json
import random

# Fungsi untuk membuat wallet Ethereum
def generate_ethereum_wallet():
    account = Account.create()
    return account.address, account._private_key.hex()  # Gunakan _private_key, bukan privateKey

# Fungsi untuk login dan bind referral code
def login_and_bind_referral(wallet_address, private_key, referral_code):
    url_login = "https://sosovalue.com/exp"  # Ganti dengan URL login yang benar
    url_bind_referral = "https://sosovalue.com/exp/bind_referral"  # Ganti dengan URL untuk binding referral code
    
    # Payload untuk login (misalnya wallet_address dan private_key, sesuaikan dengan yang diperlukan oleh situs)
    payload_login = {
        "address": wallet_address,
        "privateKey": private_key,
        "nonce": random.randint(100000, 999999)  # Nonce acak, sesuaikan jika diperlukan
    }

    # Headers jika diperlukan (sesuaikan dengan yang diharapkan oleh situs)
    headers = {
        "Content-Type": "application/json",
    }
    
    try:
        # Melakukan request POST ke situs untuk login
        response_login = requests.post(url_login, data=json.dumps(payload_login), headers=headers)
        
        if response_login.status_code == 200:
            print(f"Login successful for wallet {wallet_address}")
            
            # Jika login berhasil, bind referral code
            payload_referral = {
                "address": wallet_address,
                "referralCode": referral_code
            }

            # Mengirim request untuk binding referral code
            response_referral = requests.post(url_bind_referral, data=json.dumps(payload_referral), headers=headers)
            
            if response_referral.status_code == 200:
                print(f"Referral code {referral_code} successfully bound to wallet {wallet_address}")
            else:
                print(f"Failed to bind referral code for wallet {wallet_address}. Status Code: {response_referral.status_code}")
                print("Response:", response_referral.text)
        else:
            print(f"Login failed for wallet {wallet_address}. Status Code: {response_login.status_code}")
            print("Response:", response_login.text)
    except Exception as e:
        print(f"Error occurred: {str(e)}")

# Fungsi utama untuk menjalankan proses
def main():
    # Meminta input dari user untuk referral code
    referral_code = input("Masukkan Referral Code: ").strip()
    
    if not referral_code:
        print("Referral code tidak valid.")
        return

    # Membuat wallet Ethereum
    wallet_address, private_key = generate_ethereum_wallet()
    print(f"Generated Wallet Address: {wallet_address}")
    print(f"Private Key: {private_key}")
    
    # Melakukan login dan binding referral code
    login_and_bind_referral(wallet_address, private_key, referral_code)

# Menjalankan script
if __name__ == "__main__":
    main()
