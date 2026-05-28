// BiteWise AI Food Recommendation System - Interactive JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // 1. Theme Toggle Logic
    const themeToggleBtn = document.getElementById('themeToggleBtn');
    const body = document.body;
    
    // Check local storage for theme preference
    if (localStorage.getItem('theme') === 'light') {
        body.classList.add('light-theme');
        if (themeToggleBtn) {
            themeToggleBtn.innerHTML = '<i class="fa-solid fa-sun"></i>';
        }
    }
    
    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', function() {
            body.classList.toggle('light-theme');
            const isLight = body.classList.contains('light-theme');
            localStorage.setItem('theme', isLight ? 'light' : 'dark');
            themeToggleBtn.innerHTML = isLight ? '<i class="fa-solid fa-sun"></i>' : '<i class="fa-solid fa-moon"></i>';
        });
    }

    // 2. Budget Range Slider Display Update
    const budgetSlider = document.getElementById('budgetSlider');
    const budgetValDisplay = document.getElementById('budgetVal');
    
    if (budgetSlider && budgetValDisplay) {
        budgetSlider.addEventListener('input', function() {
            budgetValDisplay.textContent = '₹' + this.value;
        });
    }

    // 3. Option Cards Selector Helper (converts cards into form inputs)
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

    // 4. Stars Rating Hover and Click Logic on Food Cards
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
});
