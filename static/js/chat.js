// BiteWise AI Food Recommendation System - Chatbot JavaScript

document.addEventListener('DOMContentLoaded', function() {
    const chatbotWidget = document.getElementById('chatbotWidget');
    const chatbotTrigger = document.getElementById('chatbotTrigger');
    const chatDrawer = document.getElementById('chatDrawer');
    const chatClose = document.getElementById('chatClose');
    const chatForm = document.getElementById('chatForm');
    const chatInput = document.getElementById('chatInput');
    const chatMessages = document.getElementById('chatMessages');

    if (!chatbotTrigger || !chatDrawer || !chatClose) return;

    // Toggle Chat Drawer
    chatbotTrigger.addEventListener('click', function(e) {
        e.stopPropagation();
        chatDrawer.classList.toggle('open');
        if (chatDrawer.classList.contains('open')) {
            chatInput.focus();
            // Remove pulse indicator when chat is opened
            const pulse = chatbotTrigger.querySelector('.pulse-indicator');
            if (pulse) pulse.style.display = 'none';
        }
    });

    chatClose.addEventListener('click', function(e) {
        e.stopPropagation();
        chatDrawer.classList.remove('open');
    });

    // Close chat drawer when clicking outside
    document.addEventListener('click', function(e) {
        if (!chatDrawer.contains(e.target) && !chatbotTrigger.contains(e.target)) {
            chatDrawer.classList.remove('open');
        }
    });

    // Handle Form Submission
    chatForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const messageText = chatInput.value.trim();
        if (!messageText) return;
        
        // Append user message
        appendMessage('user', messageText);
        chatInput.value = '';
        
        // Append typing indicator
        const typingId = appendTypingIndicator();
        
        // Fetch API response
        fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ message: messageText })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            removeTypingIndicator(typingId);
            
            // Append bot reply
            if (data.reply) {
                appendMessage('bot', data.reply);
            } else {
                appendMessage('bot', "Sorry, I encountered an issue processing your request.");
            }
        })
        .catch(error => {
            console.error('Error:', error);
            removeTypingIndicator(typingId);
            appendMessage('bot', "I'm having trouble connecting to the recommendation server. Please try again later.");
        });
    });

    // Message Helper Functions
    function appendMessage(sender, text) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', sender);
        
        const bubble = document.createElement('div');
        bubble.classList.add('message-bubble');
        bubble.innerHTML = text; // Allowing innerHTML to render formatted recommendation links
        
        messageDiv.appendChild(bubble);
        chatMessages.appendChild(messageDiv);
        
        // Scroll to bottom
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function appendTypingIndicator() {
        const typingDiv = document.createElement('div');
        typingDiv.classList.add('message', 'bot', 'typing-indicator-msg');
        const id = 'typing_' + Date.now();
        typingDiv.setAttribute('id', id);
        
        const bubble = document.createElement('div');
        bubble.classList.add('message-bubble');
        bubble.innerHTML = '<i class="fa-solid fa-ellipsis fa-bounce"></i> BiteWise is thinking...';
        
        typingDiv.appendChild(bubble);
        chatMessages.appendChild(typingDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        
        return id;
    }

    function removeTypingIndicator(id) {
        const element = document.getElementById(id);
        if (element) {
            element.remove();
        }
    }
});
