---
name: universal-credit
description: Universal Credit Application Form Guide
sections:
  - id: housing
    title: Housing Section
    questions:
      - id: rent_or_own
        type: choice
        choices: ["rent", "own", "mortgage", "neither"]
        prompt: "Do you rent, own, pay a mortgage, or live rent-free?"
        validation:
          required: true
      - id: postcode
        type: postcode
        prompt: "What is your UK postcode?"
        validation:
          required: true
      - id: housing_costs
        type: number
        prompt: "What are your monthly housing costs (rent/mortgage) in £?"
        condition: "rent_or_own in ['rent', 'mortgage']"
        validation:
          required: true
  - id: income_savings
    title: Income & Savings Section
    questions:
      - id: has_savings
        type: boolean
        prompt: "Do you have any savings or capital?"
        validation:
          required: true
      - id: savings_amount
        type: number
        prompt: "What is the total value of your savings/capital in £?"
        condition: "has_savings == True"
        validation:
          required: true
      - id: monthly_income
        type: number
        prompt: "What is your monthly take-home pay or other income in £?"
        validation:
          required: true
  - id: childcare
    title: Childcare Section
    questions:
      - id: has_children
        type: boolean
        prompt: "Do you have dependent children?"
        validation:
          required: true
      - id: childcare_costs
        type: number
        prompt: "What are your monthly childcare costs in £?"
        condition: "has_children == True"
        validation:
          required: true
  - id: health
    title: Health Section
    questions:
      - id: health_condition
        type: boolean
        prompt: "Do you have a health condition or disability that affects your ability to work?"
        validation:
          required: true
      - id: health_details
        type: text
        prompt: "Please provide a brief description of your health condition/disability."
        condition: "health_condition == True"
        validation:
          required: true
rules:
  - name: savings_eligibility
    field: savings_amount
    threshold: 16000
    action: ineligible
    message: "Based on the £16,000 savings eligibility threshold, you are not eligible to claim Universal Credit."
---
# Universal Credit Skill

This skill contains the configuration, questions, validation rules, and thresholds for the Universal Credit application helper.
The orchestrator loads this file dynamically to drive the conversational flow.
