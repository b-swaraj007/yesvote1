// Import the functions you need from the SDKs you need
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-app.js";
import { getAuth, signInWithEmailAndPassword, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-auth.js";

// Your web app's Firebase configuration
const firebaseConfig = {
    // Replace with your Firebase config
    apiKey: "AIzaSyDBwyRyu1HqmyBHT5wkmxy2B9CQiF-Ai84",
    authDomain: "lets-vote-c3a70.firebaseapp.com",
    projectId: "lets-vote-c3a70",
    storageBucket: "lets-vote-c3a70.firebasestorage.app",
    messagingSenderId: "729264255063",
    appId: "1:729264255063:web:f128d98a38fd9e842ef312"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);

export { auth, signInWithEmailAndPassword, onAuthStateChanged }; 