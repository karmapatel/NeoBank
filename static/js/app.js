document.addEventListener('DOMContentLoaded', () => {
  // 1. Toast Notification Manager
  window.showToast = function(message, type = 'success') {
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container';
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
        <polyline points="22 4 12 14.01 9 11.01"></polyline>
      </svg>
      <span>${message}</span>
    `;

    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 3200);
  };

  // 2. Copy-to-Clipboard Helper
  document.querySelectorAll('[data-copy]').forEach(el => {
    el.addEventListener('click', () => {
      const textToCopy = el.getAttribute('data-copy');
      navigator.clipboard.writeText(textToCopy).then(() => {
        showToast(`Copied "${textToCopy}" to clipboard!`, 'info');
      }).catch(err => {
        console.error('Copy failed:', err);
      });
    });
  });

  // 3. Balance Privacy Toggle
  const privacyToggle = document.getElementById('privacy-toggle-btn');
  let isMasked = localStorage.getItem('neobank_masked') === 'true';

  function applyMasking() {
    document.querySelectorAll('.maskable-balance').forEach(el => {
      if (!el.getAttribute('data-original')) {
        el.setAttribute('data-original', el.textContent.trim());
      }
      if (isMasked) {
        el.textContent = '••••••••';
      } else {
        el.textContent = el.getAttribute('data-original');
      }
    });

    if (privacyToggle) {
      const label = privacyToggle.querySelector('.toggle-label');
      if (label) {
        label.textContent = isMasked ? 'Reveal Balances' : 'Hide Balances';
      }
    }
  }

  if (privacyToggle) {
    privacyToggle.addEventListener('click', () => {
      isMasked = !isMasked;
      localStorage.setItem('neobank_masked', isMasked);
      applyMasking();
      showToast(isMasked ? 'Balances hidden for privacy' : 'Balances revealed', 'info');
    });
    applyMasking();
  }

  // 4. Quick Amount Chips
  document.querySelectorAll('.amount-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const amount = chip.getAttribute('data-amount');
      const targetInput = document.getElementById(chip.getAttribute('data-target') || 'amount');
      if (targetInput) {
        targetInput.value = amount;
        targetInput.dispatchEvent(new Event('input'));
        targetInput.focus();
      }
    });
  });

  // 5. Dynamic Credit Underwriting & Category-Aware Loan Calculator (on /loans page)
  const creditScoreInput = document.getElementById('credit_score_input');
  const monthlyIncomeInput = document.getElementById('monthly_income_input');
  const loanSlider = document.getElementById('loan-amount-slider');
  const termSlider = document.getElementById('loan-term-slider');
  const loanAmountDisplay = document.getElementById('calc-amount-display');
  const loanTermDisplay = document.getElementById('calc-term-display');
  const loanEmiDisplay = document.getElementById('calc-emi-display');
  const loanInterestDisplay = document.getElementById('calc-interest-display');
  const loanTotalDisplay = document.getElementById('calc-total-display');
  const loanRateDisplay = document.getElementById('calc-rate-display');
  const tierBadge = document.getElementById('underwriting-tier-badge');
  const multiplierTag = document.getElementById('income-multiplier-tag');
  const maxLimitDisplay = document.getElementById('max-allowed-amount-display');
  const summaryMaxLimit = document.getElementById('summary-max-limit');
  const sliderMaxHint = document.getElementById('slider-max-hint');
  const sliderMinHint = document.getElementById('slider-min-hint');
  const sliderMinTermHint = document.getElementById('slider-min-term-hint');
  const sliderMaxTermHint = document.getElementById('slider-max-term-hint');
  const summaryCategoryBadge = document.getElementById('summary-category-badge');
  const categoryNameLimitHint = document.getElementById('category-name-limit-hint');
  const ineligibilityWarning = document.getElementById('ineligibility-warning');
  const ineligibilityReason = document.getElementById('ineligibility-reason-text');
  const submitBtn = document.getElementById('loan-submit-btn');
  const rateBreakdownTag = document.getElementById('rate-breakdown-tag');
  const foirDisplay = document.getElementById('calc-foir-display');
  const formCategory = document.getElementById('loan-form-category');
  const purposeSelect = document.getElementById('purpose');
  const categoryButtons = document.querySelectorAll('.category-select-btn');

  const CATEGORY_CONFIG = {
    home: {
      name: 'Home Loan',
      maxCap: 15000000, // ₹1.5 Crore
      minAmount: 50000,
      minTenure: 24,
      maxTenure: 300,   // 25 Years (300 Months)
      stepTenure: 6,
      defaultTenure: 240, // 20 Years
      defaultAmount: 2500000,
      tiers: {
        800: { multiplier: 75.0, maxCap: 15000000, baseRate: 8.40, name: 'Super Prime' },
        750: { multiplier: 60.0, maxCap: 12500000, baseRate: 8.65, name: 'Prime' },
        700: { multiplier: 45.0, maxCap: 10000000, baseRate: 8.95, name: 'Good' },
        650: { multiplier: 30.0, maxCap: 6000000,  baseRate: 9.50, name: 'Fair' },
        600: { multiplier: 15.0, maxCap: 3000000,  baseRate: 10.50, name: 'Subprime Eligible' }
      },
      purposes: [
        { value: 'Home Purchase / Construction', label: 'New Flat / Home Purchase or Construction' },
        { value: 'Home Renovation & Solar', label: 'Home Renovation, Extension & Rooftop Solar' },
        { value: 'Plot & Villa Development', label: 'Residential Plot & Villa Development' }
      ]
    },
    auto: {
      name: 'Car / Auto Loan',
      maxCap: 4000000,  // ₹40 Lakh
      minAmount: 25000,
      minTenure: 12,
      maxTenure: 84,    // 7 Years (84 Months)
      stepTenure: 6,
      defaultTenure: 48, // 4 Years
      defaultAmount: 800000,
      tiers: {
        800: { multiplier: 20.0, maxCap: 4000000, baseRate: 8.75, name: 'Super Prime' },
        750: { multiplier: 16.0, maxCap: 3500000, baseRate: 9.15, name: 'Prime' },
        700: { multiplier: 12.0, maxCap: 2500000, baseRate: 9.75, name: 'Good' },
        650: { multiplier: 8.0,  maxCap: 1500000, baseRate: 10.75, name: 'Fair' },
        600: { multiplier: 4.0,  maxCap: 800000,  baseRate: 12.00, name: 'Subprime Eligible' }
      },
      purposes: [
        { value: 'New Passenger Car / Electric Vehicle (EV)', label: 'New Passenger Car / Electric Vehicle (EV)' },
        { value: 'Commercial Fleet / Transport', label: 'Commercial Fleet / Utility Transport' },
        { value: 'Certified Pre-Owned Car', label: 'Certified Pre-Owned Car' }
      ]
    },
    business: {
      name: 'Business Loan',
      maxCap: 7500000,  // ₹75 Lakh
      minAmount: 50000,
      minTenure: 12,
      maxTenure: 120,   // 10 Years (120 Months)
      stepTenure: 6,
      defaultTenure: 60,
      defaultAmount: 1500000,
      tiers: {
        800: { multiplier: 35.0, maxCap: 7500000, baseRate: 9.75, name: 'Super Prime' },
        750: { multiplier: 28.0, maxCap: 6000000, baseRate: 10.50, name: 'Prime' },
        700: { multiplier: 20.0, maxCap: 4500000, baseRate: 11.50, name: 'Good' },
        650: { multiplier: 12.0, maxCap: 2500000, baseRate: 12.75, name: 'Fair' },
        600: { multiplier: 6.0,  maxCap: 1200000, baseRate: 14.00, name: 'Subprime Eligible' }
      },
      purposes: [
        { value: 'Business Expansion & Working Capital', label: 'Business Scaling & Working Capital' },
        { value: 'Machinery & Commercial Setup', label: 'Machinery & Commercial Equipment' },
        { value: 'Store & Branch Expansion', label: 'Store & Branch Expansion' }
      ]
    },
    education: {
      name: 'Higher Education Loan',
      maxCap: 5000000,  // ₹50 Lakh
      minAmount: 25000,
      minTenure: 12,
      maxTenure: 180,   // 15 Years (180 Months)
      stepTenure: 12,
      defaultTenure: 84,
      defaultAmount: 1000000,
      tiers: {
        800: { multiplier: 30.0, maxCap: 5000000, baseRate: 8.50, name: 'Super Prime' },
        750: { multiplier: 24.0, maxCap: 4000000, baseRate: 8.90, name: 'Prime' },
        700: { multiplier: 18.0, maxCap: 3000000, baseRate: 9.40, name: 'Good' },
        650: { multiplier: 10.0, maxCap: 1800000, baseRate: 10.20, name: 'Fair' },
        600: { multiplier: 5.0,  maxCap: 1000000, baseRate: 11.50, name: 'Subprime Eligible' }
      },
      purposes: [
        { value: 'Higher Education / Overseas Study', label: 'Higher Education / Overseas University' },
        { value: 'Executive & Professional Tech Training', label: 'Executive & Technical Certifications' },
        { value: 'Undergraduate Tuition & Campus Fee', label: 'Undergraduate Tuition & College Fee' }
      ]
    },
    personal: {
      name: 'Personal Loan',
      maxCap: 5000000,  // ₹50 Lakh max cap
      minAmount: 10000,
      minTenure: 6,
      maxTenure: 60,    // 5 Years (60 Months)
      stepTenure: 6,
      defaultTenure: 24,
      defaultAmount: 200000,
      tiers: {
        800: { multiplier: 25.0, maxCap: 5000000, baseRate: 7.50, name: 'Super Prime' },
        750: { multiplier: 18.0, maxCap: 3500000, baseRate: 8.50, name: 'Prime' },
        700: { multiplier: 12.0, maxCap: 2000000, baseRate: 9.90, name: 'Good' },
        650: { multiplier: 8.0,  maxCap: 1000000, baseRate: 11.75, name: 'Fair' },
        600: { multiplier: 4.0,  maxCap: 400000,  baseRate: 13.50, name: 'Subprime Eligible' }
      },
      purposes: [
        { value: 'Personal Liquidity / Medical Contingency', label: 'Personal Liquidity & Medical Emergency' },
        { value: 'Professional Computing & Gadgets', label: 'Hardware & Home Electronics' },
        { value: 'Family Function & Travel', label: 'Wedding & Family Functions' }
      ]
    }
  };

  let currentCategory = (formCategory && formCategory.value) || 'home';
  if (!CATEGORY_CONFIG[currentCategory]) currentCategory = 'home';

  function updateCategory(newCat) {
    if (!CATEGORY_CONFIG[newCat]) return;
    currentCategory = newCat;
    if (formCategory) formCategory.value = newCat;

    // Update active button styles
    categoryButtons.forEach(btn => {
      if (btn.getAttribute('data-category') === newCat) {
        btn.className = 'category-card-btn category-select-btn btn-primary active';
      } else {
        btn.className = 'category-card-btn category-select-btn';
      }
    });

    const config = CATEGORY_CONFIG[newCat];
    const calcSectionTitle = document.getElementById('calculator-section-title');
    if (calcSectionTitle) {
      calcSectionTitle.textContent = `Configure ${config.name}`;
    }

    // Update term slider attributes
    if (termSlider) {
      termSlider.min = config.minTenure;
      termSlider.max = config.maxTenure;
      termSlider.step = config.stepTenure || 6;
      termSlider.value = config.defaultTenure;
    }

    if (sliderMinTermHint) {
      const minYears = Math.floor(config.minTenure / 12);
      sliderMinTermHint.textContent = `${config.minTenure} Months${minYears > 0 ? ` (${minYears} Yrs)` : ''}`;
    }
    if (sliderMaxTermHint) {
      const maxYears = Math.floor(config.maxTenure / 12);
      sliderMaxTermHint.textContent = `${config.maxTenure} Months (${maxYears} Years)`;
    }

    if (summaryCategoryBadge) {
      summaryCategoryBadge.textContent = config.name;
    }
    if (categoryNameLimitHint) {
      categoryNameLimitHint.textContent = config.name;
    }

    // Update purpose dropdown options
    if (purposeSelect && config.purposes) {
      purposeSelect.innerHTML = '';
      config.purposes.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.value;
        opt.textContent = p.label;
        purposeSelect.appendChild(opt);
      });
    }

    calculateLoan(true);
  }

  function calculateLoan(resetAmountToDefault = false) {
    if (!loanSlider || !termSlider) return;

    const config = CATEGORY_CONFIG[currentCategory] || CATEGORY_CONFIG.home;
    const creditScore = parseInt(creditScoreInput ? creditScoreInput.value : 760) || 760;
    const monthlyIncome = parseFloat(monthlyIncomeInput ? monthlyIncomeInput.value : 75000) || 0;

    // Check hard underwriting thresholds
    let isEligible = true;
    let failReason = '';

    if (creditScore < 600) {
      isEligible = false;
      failReason = `CIBIL score (${creditScore}) is below minimum mandatory threshold of 600. Application cannot be approved.`;
    } else if (monthlyIncome < 20000) {
      isEligible = false;
      failReason = `Monthly income of ₹${monthlyIncome.toLocaleString('en-IN')} is below the minimum baseline requirement of ₹20,000.`;
    }

    if (!isEligible) {
      if (ineligibilityWarning) {
        ineligibilityWarning.style.display = 'block';
        if (ineligibilityReason) ineligibilityReason.textContent = failReason;
      }
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.style.opacity = '0.5';
        submitBtn.style.cursor = 'not-allowed';
        submitBtn.textContent = 'Ineligible for Sanctioning';
      }
      if (tierBadge) {
        tierBadge.textContent = 'Ineligible';
        tierBadge.className = 'badge badge-danger';
      }
      if (maxLimitDisplay) maxLimitDisplay.textContent = '₹0.00';
      if (summaryMaxLimit) summaryMaxLimit.textContent = '₹0.00';
      return;
    } else {
      if (ineligibilityWarning) ineligibilityWarning.style.display = 'none';
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.style.opacity = '1';
        submitBtn.style.cursor = 'pointer';
        submitBtn.textContent = 'Disburse Sanctioned Funds →';
      }
    }

    // Determine category tier, multiplier & base rate based on credit score
    let tierInfo = config.tiers[600];
    const cutoffs = [800, 750, 700, 650, 600];
    for (let c of cutoffs) {
      if (creditScore >= c && config.tiers[c]) {
        tierInfo = config.tiers[c];
        break;
      }
    }

    const multiplier = tierInfo.multiplier;
    const maxCap = tierInfo.maxCap;
    const baseRate = tierInfo.baseRate;
    const tierName = tierInfo.name;

    let tierClass = 'badge badge-info';
    if (creditScore >= 750) tierClass = 'badge badge-success';
    else if (creditScore < 650) tierClass = 'badge badge-warning';

    if (tierBadge) {
      tierBadge.textContent = `${tierName} (${config.name})`;
      tierBadge.className = tierClass;
    }
    if (multiplierTag) {
      multiplierTag.textContent = `${multiplier}x Limit`;
    }

    // Category Max loan amount strictly determined by Income and Credit Score multiplier
    const maxLoanAmount = Math.max(config.minAmount, Math.min(maxCap, Math.round((monthlyIncome * multiplier) / 100) * 100));

    // Update slider bounds dynamically
    loanSlider.min = config.minAmount;
    loanSlider.max = maxLoanAmount;
    loanSlider.step = maxLoanAmount > 2000000 ? 50000 : (maxLoanAmount > 500000 ? 25000 : 10000);

    if (resetAmountToDefault) {
      loanSlider.value = Math.min(config.defaultAmount, maxLoanAmount);
    } else {
      if (parseFloat(loanSlider.value) > maxLoanAmount) {
        loanSlider.value = maxLoanAmount;
      } else if (parseFloat(loanSlider.value) < config.minAmount) {
        loanSlider.value = config.minAmount;
      }
    }

    // Check tenure bounds
    let term = parseInt(termSlider.value) || config.defaultTenure;
    if (term > config.maxTenure) {
      term = config.maxTenure;
      termSlider.value = term;
    } else if (term < config.minTenure) {
      term = config.minTenure;
      termSlider.value = term;
    }

    const amount = parseFloat(loanSlider.value);

    // Monthly Income Rate Concession / Risk Adjustment
    let incomeDiscount = 0.0;
    let incomeLabel = 'Standard rate';
    if (currentCategory === 'personal') {
      if (monthlyIncome >= 150000) {
        incomeDiscount = -0.75;
        incomeLabel = 'Income rebate: -0.75%';
      } else if (monthlyIncome >= 100000) {
        incomeDiscount = -0.50;
        incomeLabel = 'Income rebate: -0.50%';
      } else if (monthlyIncome >= 50000) {
        incomeDiscount = -0.25;
        incomeLabel = 'Income rebate: -0.25%';
      } else if (monthlyIncome < 30000) {
        incomeDiscount = 0.50;
        incomeLabel = 'Low-income risk: +0.50%';
      }
    } else if (currentCategory === 'home') {
      if (monthlyIncome >= 150000) {
        incomeDiscount = -0.30;
        incomeLabel = 'HNW rebate: -0.30%';
      } else if (monthlyIncome >= 100000) {
        incomeDiscount = -0.20;
        incomeLabel = 'Salaried rebate: -0.20%';
      } else if (monthlyIncome >= 50000) {
        incomeDiscount = -0.10;
        incomeLabel = 'Income rebate: -0.10%';
      }
    } else {
      if (monthlyIncome >= 150000) {
        incomeDiscount = -0.40;
        incomeLabel = 'Income rebate: -0.40%';
      } else if (monthlyIncome >= 100000) {
        incomeDiscount = -0.25;
        incomeLabel = 'Income rebate: -0.25%';
      } else if (monthlyIncome >= 50000) {
        incomeDiscount = -0.15;
        incomeLabel = 'Income rebate: -0.15%';
      }
    }

    // Tenure adjustment
    let tenureAdj = 0.0;
    if (currentCategory === 'home') {
      if (term > 180) tenureAdj = 0.20;
    } else if (currentCategory === 'personal') {
      if (term > 36) tenureAdj = 0.50;
      else if (term > 12) tenureAdj = 0.25;
    } else {
      if (term > 60) tenureAdj = 0.25;
    }

    const rate = Math.max(6.99, +(baseRate + incomeDiscount + tenureAdj).toFixed(2));

    const monthlyRate = (rate / 100) / 12;
    let emi = 0;
    if (monthlyRate > 0) {
      emi = (amount * monthlyRate * Math.pow(1 + monthlyRate, term)) / (Math.pow(1 + monthlyRate, term) - 1);
    } else {
      emi = amount / term;
    }

    const totalPayable = emi * term;
    const totalInterest = totalPayable - amount;
    const foirPercent = monthlyIncome > 0 ? ((emi / monthlyIncome) * 100).toFixed(1) : 0;

    // Display updates
    if (maxLimitDisplay) maxLimitDisplay.textContent = `₹${maxLoanAmount.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
    if (summaryMaxLimit) summaryMaxLimit.textContent = `₹${maxLoanAmount.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
    if (sliderMaxHint) sliderMaxHint.textContent = `Max Cap: ₹${maxLoanAmount.toLocaleString('en-IN')}`;
    if (sliderMinHint) sliderMinHint.textContent = `Min: ₹${config.minAmount.toLocaleString('en-IN')}`;

    if (loanAmountDisplay) loanAmountDisplay.textContent = `₹${amount.toLocaleString('en-IN')}`;
    
    const years = (term / 12).toFixed(term % 12 === 0 ? 0 : 1);
    if (loanTermDisplay) loanTermDisplay.textContent = `${term} Months (${years} ${years === '1' ? 'Year' : 'Years'})`;
    
    if (loanRateDisplay) loanRateDisplay.textContent = `${rate.toFixed(2)}% p.a.`;
    if (rateBreakdownTag) rateBreakdownTag.textContent = `${config.name} Base: ${baseRate}% | ${incomeLabel}`;
    if (loanEmiDisplay) loanEmiDisplay.textContent = `₹${emi.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    if (loanInterestDisplay) loanInterestDisplay.textContent = `₹${totalInterest.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    if (loanTotalDisplay) loanTotalDisplay.textContent = `₹${totalPayable.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    if (foirDisplay) foirDisplay.textContent = `${foirPercent}% of Income`;

    // Sync hidden form inputs for backend POST
    const formAmount = document.getElementById('loan-form-amount');
    const formTerm = document.getElementById('loan-form-term');
    const formScore = document.getElementById('loan-form-score');
    const formIncome = document.getElementById('loan-form-income');
    if (formCategory) formCategory.value = currentCategory;
    if (formAmount) formAmount.value = amount;
    if (formTerm) formTerm.value = term;
    if (formScore) formScore.value = creditScore;
    if (formIncome) formIncome.value = monthlyIncome;
  }

  // Bind category button clicks
  categoryButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const cat = btn.getAttribute('data-category');
      updateCategory(cat);
    });
  });

  if (loanSlider && termSlider) {
    loanSlider.addEventListener('input', () => calculateLoan(false));
    termSlider.addEventListener('input', () => calculateLoan(false));
    if (creditScoreInput) creditScoreInput.addEventListener('input', () => calculateLoan(false));
    if (monthlyIncomeInput) monthlyIncomeInput.addEventListener('input', () => calculateLoan(false));
    calculateLoan(false);
  }

  // 6. Recipient Live Verification during Transfer
  const recipientInput = document.getElementById('recipient_account');
  const recipientFeedback = document.getElementById('recipient-feedback');

  if (recipientInput && recipientFeedback) {
    let debounceTimer;
    recipientInput.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      const query = recipientInput.value.trim();
      if (query.length < 3) {
        recipientFeedback.innerHTML = '';
        return;
      }

      debounceTimer = setTimeout(() => {
        fetch(`/api/lookup-account?query=${encodeURIComponent(query)}`)
          .then(res => res.json())
          .then(data => {
            if (data.found) {
              recipientFeedback.innerHTML = `
                <div style="display:flex; align-items:center; gap:8px; margin-top:8px; font-size:0.85rem; color:var(--accent-mint);">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                  <span>Verified: <strong>${data.name}</strong> (${data.account_number})</span>
                </div>
              `;
            } else {
              recipientFeedback.innerHTML = `
                <div style="display:flex; align-items:center; gap:8px; margin-top:8px; font-size:0.85rem; color:var(--text-tertiary);">
                  <span>Searching for verified NeoBank account...</span>
                </div>
              `;
            }
          })
          .catch(() => {});
      }, 300);
    });
  }

  // 7. Virtual Card Number / CVV Toggle
  const revealCardBtn = document.getElementById('toggle-card-details-btn');
  if (revealCardBtn) {
    revealCardBtn.addEventListener('click', () => {
      const cardNumber = document.getElementById('virtual-card-number');
      const cardCvv = document.getElementById('virtual-card-cvv');
      const isRevealed = revealCardBtn.getAttribute('data-revealed') === 'true';

      if (isRevealed) {
        if (cardNumber) cardNumber.textContent = cardNumber.getAttribute('data-masked');
        if (cardCvv) cardCvv.textContent = '•••';
        revealCardBtn.setAttribute('data-revealed', 'false');
        revealCardBtn.querySelector('span').textContent = 'Reveal Details';
      } else {
        if (cardNumber) cardNumber.textContent = cardNumber.getAttribute('data-raw');
        if (cardCvv) cardCvv.textContent = cardCvv.getAttribute('data-raw');
        revealCardBtn.setAttribute('data-revealed', 'true');
        revealCardBtn.querySelector('span').textContent = 'Hide Details';
        showToast('Card numbers visible for 30 seconds', 'info');
      }
    });
  }

  // 8. Tab Switcher
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-target');
      const container = btn.closest('.tabs-wrapper');
      if (!container) return;

      container.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      container.querySelectorAll('.tab-pane').forEach(p => p.style.display = 'none');

      btn.classList.add('active');
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.style.display = 'block';
    });
  });

  // 9. Client-side Instant Filter for Transaction Rows
  const tableSearch = document.getElementById('table-search-input');
  if (tableSearch) {
    tableSearch.addEventListener('input', () => {
      const val = tableSearch.value.toLowerCase();
      document.querySelectorAll('.transaction-row').forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(val) ? '' : 'none';
      });
    });
  }

  // 10. Real-time Extra Loan Payment & Updated EMI Calculation
  window.updateExtraPreview = function(loanId, annualRate, currentEmi, remainingPayable) {
    const input = document.getElementById(`extra_input_${loanId}`);
    const tenureInput = document.getElementById(`tenure_input_${loanId}`);
    const preview = document.getElementById(`extra_preview_${loanId}`);
    const prevPrincipal = document.getElementById(`prev_principal_${loanId}`);
    const prevFee = document.getElementById(`prev_fee_${loanId}`);
    const prevTotal = document.getElementById(`prev_total_${loanId}`);
    const prevNewEmi = document.getElementById(`prev_new_emi_${loanId}`);

    if (!input || !preview) return;

    const val = parseFloat(input.value);
    if (!val || val <= 0) {
      preview.style.display = 'none';
      return;
    }

    const fee = val * 0.123;
    const total = val + fee;

    prevPrincipal.textContent = `₹${val.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    prevFee.textContent = `₹${fee.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    prevTotal.textContent = `₹${total.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;

    if (prevNewEmi && annualRate && currentEmi) {
      let tenure = tenureInput ? parseInt(tenureInput.value, 10) : 0;
      if (!tenure || tenure <= 0) {
        tenure = Math.max(1, Math.round(remainingPayable / currentEmi));
      }
      const r = (annualRate / 100.0) / 12.0;
      let newEmi = 0;
      if (r > 0 && tenure > 0) {
        const pv = currentEmi * (1 - Math.pow(1 + r, -tenure)) / r;
        const newPrincipal = Math.max(0, pv - val);
        if (newPrincipal > 0) {
          newEmi = (newPrincipal * r * Math.pow(1 + r, tenure)) / (Math.pow(1 + r, tenure) - 1);
        }
      } else if (tenure > 0) {
        const newPrincipal = Math.max(0, remainingPayable - val);
        newEmi = newPrincipal / tenure;
      }
      const drop = Math.max(0, currentEmi - newEmi);
      prevNewEmi.innerHTML = `✨ New Monthly EMI: <strong class="mono-num">₹${newEmi.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</strong> (${tenure} mos) &bull; <span style="color: #047857;">Saves ₹${drop.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}/mo</span>`;
    }

    preview.style.display = 'block';
  };

  // 11. Autonomous Banking Cycle Trigger Handler
  const autoCycleBtn = document.getElementById('run-auto-cycle-btn');
  if (autoCycleBtn) {
    autoCycleBtn.addEventListener('click', async () => {
      autoCycleBtn.disabled = true;
      const originalHtml = autoCycleBtn.innerHTML;
      autoCycleBtn.innerHTML = `
        <svg class="animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation: spin 1s linear infinite;">
          <circle cx="12" cy="12" r="10" stroke-dasharray="30" stroke-dashoffset="10"></circle>
        </svg>
        <span>Running Cycle...</span>
      `;

      try {
        const resp = await fetch('/api/auto-cycle/run-daily?force=true', { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
          if (data.status === 'already_processed') {
            showToast(`⚡ Daily Banking Cycle for today (${data.date}) was already completed. Next cycle will check at 12:00 AM Midnight.`, 'info');
            autoCycleBtn.disabled = false;
            autoCycleBtn.innerHTML = originalHtml;
            return;
          }

          let msg = '⚡ Daily Banking Cycle Executed! ';
          if (data.user_stats) {
            const u = data.user_stats;
            const parts = [];
            if (u.accounts_credited > 0) {
              parts.push(`Credited ₹${u.interest_credited.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})} interest across your ${u.accounts_credited} account${u.accounts_credited > 1 ? 's' : ''}`);
            } else {
              parts.push('No interest accrued on your accounts');
            }
            if (u.loans_debited > 0) {
              parts.push(`auto-debited ₹${u.emi_debited.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})} daily loan interest (monthly EMI updated)`);
            }
            msg += parts.join(' & ') + '.';
          } else {
            msg += `Credited ₹${data.total_interest_credited.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})} interest (${data.accounts_credited} a/c) & auto-debited ₹${data.total_emi_debited.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2})} daily loan interest (${data.loans_debited} loans).`;
          }

          showToast(msg, 'success');
          setTimeout(() => window.location.reload(), 1800);
        } else {
          showToast(data.message || 'Auto-cycle executed.', 'info');
          autoCycleBtn.disabled = false;
          autoCycleBtn.innerHTML = originalHtml;
        }
      } catch (err) {
        showToast('Error triggering banking cycle.', 'error');
        autoCycleBtn.disabled = false;
        autoCycleBtn.innerHTML = originalHtml;
      }
    });
  }
});
