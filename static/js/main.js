// BiteWise AI Food Recommendation System - Interactive JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // 1. Budget Range Slider Display Update
    const budgetSlider = document.getElementById('budgetSlider');
    const budgetValDisplay = document.getElementById('budgetVal');

    if (budgetSlider && budgetValDisplay) {
        budgetSlider.addEventListener('input', function() {
            budgetValDisplay.textContent = '₹' + this.value;
        });
    }

    // 2. Option Cards Selector Helper (converts cards into form inputs)
    setupCardSelectors('cuisine-card', 'cuisineInput');
    setupCardSelectors('diet-card', 'dietInput');
    setupCardSelectors('spice-card', 'spiceInput');
    setupCardSelectors('health-card', 'healthInput');
    setupCardSelectors('mood-card', 'moodInput');

    function setupCardSelectors(cardClass, inputId) {
        const cards = document.querySelectorAll('.' + cardClass);
        const hiddenInput = document.getElementById(inputId);

        if (cards.length > 0 && hiddenInput) {
            cards.forEach(card => {
                card.addEventListener('click', function() {
                    // Remove selected state from sibling cards
                    cards.forEach(c => c.classList.remove('selected'));

                    // Add selected state to clicked card
                    this.classList.add('selected');

                    // Set value in hidden input
                    const val = this.getAttribute('data-value');
                    hiddenInput.value = val;
                });
            });
        }
    }

    // 3. Stars Rating Hover and Click Logic on Food Cards
    const ratingContainers = document.querySelectorAll('.rating-stars');

    ratingContainers.forEach(container => {
        const stars = container.querySelectorAll('.rating-star-btn');
        const ratingInput = container.closest('.rating-action-box').querySelector('.rating-score-value');

        stars.forEach((star, index) => {
            // Hover effect
            star.addEventListener('mouseover', () => {
                stars.forEach((s, idx) => {
                    if (idx <= index) {
                        s.classList.add('hover');
                    } else {
                        s.classList.remove('hover');
                    }
                });
            });

            // Mouse leave
            star.addEventListener('mouseout', () => {
                stars.forEach(s => s.classList.remove('hover'));
            });

            // Click to lock rating value
            star.addEventListener('click', () => {
                const score = index + 1;
                ratingInput.value = score;

                stars.forEach((s, idx) => {
                    if (idx < score) {
                        s.classList.add('active');
                    } else {
                        s.classList.remove('active');
                    }
                });
            });
        });
    });

    // 4. AJAX Rating Submission
    const ratingForms = document.querySelectorAll('.rating-action-box form, form.rating-action-box');
    ratingForms.forEach(form => {
        form.addEventListener('submit', function(e) {
            e.preventDefault();

            const submitBtn = this.querySelector('.submit-rating-btn');
            const originalText = submitBtn.textContent;
            submitBtn.textContent = '...';
            submitBtn.disabled = true;

            const formData = new FormData(this);
            const data = Object.fromEntries(formData.entries());

            fetch(this.action, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                body: JSON.stringify(data)
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    submitBtn.textContent = 'Rated!';
                    submitBtn.style.backgroundColor = 'var(--success)';
                } else {
                    submitBtn.textContent = 'Error';
                    submitBtn.style.backgroundColor = 'var(--error)';
                    setTimeout(() => {
                        submitBtn.textContent = originalText;
                        submitBtn.disabled = false;
                        submitBtn.style.backgroundColor = '';
                    }, 2000);
                }
            })
            .catch(err => {
                console.error(err);
                submitBtn.textContent = 'Error';
                setTimeout(() => {
                    submitBtn.textContent = originalText;
                    submitBtn.disabled = false;
                }, 2000);
            });
        });
    });

    // 5. Save Recommendation to Hitlist
    const saveButtons = document.querySelectorAll('.save-button[data-food-id]');
    saveButtons.forEach(button => {
        button.addEventListener('click', function() {
            const originalTitle = this.getAttribute('title') || 'Save to hitlist';
            this.disabled = true;

            fetch('/save-food', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                body: JSON.stringify({ food_id: this.dataset.foodId })
            })
            .then(response => response.json().then(data => ({ ok: response.ok, data })))
            .then(({ ok, data }) => {
                if (!ok || data.status !== 'success') {
                    throw new Error(data.message || 'Unable to save dish');
                }
                this.classList.add('saved');
                this.setAttribute('title', 'Saved to hitlist');
            })
            .catch(err => {
                console.error(err);
                this.setAttribute('title', 'Could not save');
                setTimeout(() => {
                    this.setAttribute('title', originalTitle);
                    this.disabled = false;
                }, 1600);
            });
        });
    });
});
