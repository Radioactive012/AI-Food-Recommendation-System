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
                appendMessage('bot', "Oops, something went wrong on our end.");
            }
        })
        .catch(error => {
            console.error('Error:', error);
            removeTypingIndicator(typingId);
            appendMessage('bot', "Can't reach the server right now. Give it a sec and try again!");
        });
    });

    // Message Helper Functions
    function appendMessage(sender, text) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', sender);
        
        const bubble = document.createElement('div');
        bubble.classList.add('message-bubble');

        if (sender === 'bot') {
            bubble.appendChild(sanitizeBotReply(text));
        } else {
            bubble.textContent = text;
        }
        
        messageDiv.appendChild(bubble);
        chatMessages.appendChild(messageDiv);
        
        // Scroll to bottom
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function sanitizeBotReply(html) {
        const template = document.createElement('template');
        template.innerHTML = html;
        const fragment = document.createDocumentFragment();
        const allowedInlineTags = new Set(['BR', 'EM', 'STRONG', 'B', 'I']);

        function cleanNode(node, parent) {
            if (node.nodeType === Node.TEXT_NODE) {
                parent.appendChild(document.createTextNode(node.textContent));
                return;
            }

            if (node.nodeType !== Node.ELEMENT_NODE) {
                return;
            }

            if (node.tagName === 'A') {
                const href = node.getAttribute('href') || '';
                const safeLink = href.startsWith('/recommendation-direct?food_id=');
                if (safeLink) {
                    const anchor = document.createElement('a');
                    anchor.href = href;
                    anchor.className = 'chat-food-link';
                    anchor.textContent = node.textContent;
                    parent.appendChild(anchor);
                } else {
                    parent.appendChild(document.createTextNode(node.textContent));
                }
                return;
            }

            if (allowedInlineTags.has(node.tagName)) {
                const element = document.createElement(node.tagName.toLowerCase());
                Array.from(node.childNodes).forEach(child => cleanNode(child, element));
                parent.appendChild(element);
                return;
            }

            Array.from(node.childNodes).forEach(child => cleanNode(child, parent));
        }

        Array.from(template.content.childNodes).forEach(node => cleanNode(node, fragment));
        return fragment;
    }

    function appendTypingIndicator() {
        const typingDiv = document.createElement('div');
        typingDiv.classList.add('message', 'bot', 'typing-indicator-msg');
        const id = 'typing_' + Date.now();
        typingDiv.setAttribute('id', id);
        
        const bubble = document.createElement('div');
        bubble.classList.add('message-bubble');
        bubble.innerHTML = '<i class="fa-solid fa-ellipsis fa-bounce"></i> Finding something delicious...';
        
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
