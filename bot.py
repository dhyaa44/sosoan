const { Builder, By, until } = require('selenium-webdriver');
const readline = require('readline');
const fs = require('fs');

const { Web3 } = require('web3');
const web3 = new Web3();

// Static API key for login request
const STATIC_API_KEY = 'dXoriON31OO1UopGakYO9f3tX2c4q3oO7mNsjB2nJsKnW406';

console.log(`
========================
| Auto Referral Centic |
| @AirdropFamilyIdn    |
========================
`);

function generateNonce() {
  const nonce = Math.round(1e6 * Math.random());
  return nonce;
}

function signMessage(privateKey, message) {
  const account = web3.eth.accounts.privateKeyToAccount(privateKey);
  return account.sign(message).signature;
}

async function login(privateKey) {
  const account = web3.eth.accounts.privateKeyToAccount(privateKey);
  const address = account.address;
  const nonce = generateNonce();
  const message = `I am signing my one-time nonce: ${nonce}.`;
  const signature = await signMessage(privateKey, message);

  const payload = {
    address,
    nonce,
    signature
  };

  try {
    const response = await axios.post('https://develop.centic.io/dev/v3/auth/login', payload, {
      headers: { 'x-apikey': STATIC_API_KEY }
    });

    const apiKey = response.data.apiKey;
    return { apiKey, address };
  } catch (error) {
    console.error('Login failed:', error.message);
    return null;
  }
}

// WebDriver function to bind referral
async function bindReferralWithSelenium(referralCode, privateKey) {
  let driver = await new Builder().forBrowser('chrome').build();
  try {
    // Open the referral page
    await driver.get('https://sosovalue.com/exp');

    // Wait for the form or elements to load
    await driver.wait(until.elementLocated(By.id('referral-code-input')), 10000);

    // Fill the referral code field
    const referralInput = await driver.findElement(By.id('referral-code-input')); // Ganti dengan ID yang sesuai
    await referralInput.sendKeys(referralCode);

    // Submit the form
    const submitButton = await driver.findElement(By.id('submit-button')); // Ganti dengan ID yang sesuai
    await submitButton.click();

    // Wait for some result (confirmation page or message)
    await driver.wait(until.elementLocated(By.id('confirmation-message')), 10000);

    console.log(`Referral code ${referralCode} successfully bound to the account`);

    // Simpan private key ke file
    fs.appendFileSync('privatekey.txt', `${privateKey}\n`);
  } catch (error) {
    console.error('Error during Selenium interaction:', error.message);
  } finally {
    await driver.quit();
  }
}

// Main function
async function runBot(referralCode, referralInterval) {
  for (let i = 0; i < referralInterval; i++) {
    const privateKeys = [];

    const newAccount = web3.eth.accounts.create();
    privateKeys.push(newAccount.privateKey);

    for (const privateKey of privateKeys) {
      if (!isValidPrivateKey(privateKey)) {
        console.error(`Invalid private key: ${privateKey}`);
        continue;
      }

      const account = web3.eth.accounts.privateKeyToAccount(privateKey);
      const address = account.address;

      const loginResult = await login(privateKey);
      if (!loginResult) {
        continue;
      }

      const { apiKey } = loginResult;
      await bindReferralWithSelenium(referralCode, privateKey);
    }
  }
}

// Setup readline interface
const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

// Ask user for referral code and interval
rl.question('Masukkan kode Referral: ', (referralCode) => {
  if (!referralCode) {
    console.error('Kode Referral tidak valid.');
    rl.close();
    return;
  }

  rl.question('Masukkan jumlah Referral: ', (interasi) => {
    const referralInterval = parseInt(interasi);
    if (isNaN(referralInterval) || referralInterval <= 0) {
      console.error('Interval Referral tidak valid.');
      rl.close();
      return;
    }

    runBot(referralCode, referralInterval).then(() => {
      console.log('Bot selesai dijalankan.');
      rl.close();
    });
  });
});
