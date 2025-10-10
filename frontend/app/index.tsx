import React, { useState, useEffect } from 'react';
import { 
  View, 
  Text, 
  TextInput, 
  TouchableOpacity, 
  StyleSheet, 
  Alert,
  SafeAreaView,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useRouter } from 'expo-router';
import { TokenManager } from '../utils/tokenManager';

const EXPO_PUBLIC_BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

export default function LoginScreen() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleLogin = async () => {
    console.log('=== LOGIN STARTED ===');
    console.log('Username:', username);
    console.log('Password length:', password.length);
    console.log('Backend URL:', EXPO_PUBLIC_BACKEND_URL);
    
    if (!username.trim() || !password.trim()) {
      Alert.alert('Error', 'Please enter username and password');
      return;
    }

    setLoading(true);
    console.log('Loading set to true');
    
    try {
      const apiUrl = `${EXPO_PUBLIC_BACKEND_URL}/api/mobile/auth/login`;
      console.log('Full API URL:', apiUrl);
      console.log('About to call fetch...');
      
      // Test with XMLHttpRequest as fallback
      const testXHR = () => {
        return new Promise((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          const timeoutId = setTimeout(() => {
            xhr.abort();
            reject(new Error('XHR Timeout after 15 seconds'));
          }, 15000);
          
          xhr.onload = () => {
            clearTimeout(timeoutId);
            console.log('XHR completed with status:', xhr.status);
            if (xhr.status >= 200 && xhr.status < 300) {
              resolve(JSON.parse(xhr.responseText));
            } else {
              reject(new Error(`HTTP ${xhr.status}`));
            }
          };
          
          xhr.onerror = () => {
            clearTimeout(timeoutId);
            console.error('XHR error occurred');
            reject(new Error('Network error'));
          };
          
          xhr.ontimeout = () => {
            console.error('XHR timeout occurred');
            reject(new Error('Request timeout'));
          };
          
          console.log('Opening XHR connection...');
          xhr.open('POST', apiUrl);
          xhr.setRequestHeader('Content-Type', 'application/json');
          console.log('Sending XHR request...');
          xhr.send(JSON.stringify({ username, password }));
        });
      };
      
      console.log('Using XMLHttpRequest for request...');
      const data = await testXHR();
      console.log('Request completed successfully');
      console.log('Response data keys:', Object.keys(data));

      if (data.access_token) {
        console.log('Login successful! Storing tokens...');
        await TokenManager.storeTokens(
          data.access_token,
          data.refresh_token,
          data.expires_in,
          data.refresh_expires_in
        );
        
        await AsyncStorage.setItem('user', JSON.stringify({ username }));
        console.log('Tokens stored. Navigating to permits...');
        
        router.replace('/permits');
      } else {
        const errorMsg = data.detail || data.error || 'Invalid credentials';
        console.error('Login failed:', errorMsg);
        Alert.alert('Login Failed', errorMsg);
      }
    } catch (error) {
      console.error('=== LOGIN ERROR ===');
      console.error('Error name:', error.name);
      console.error('Error message:', error.message);
      
      if (error.message.includes('Timeout') || error.message.includes('timeout')) {
        Alert.alert('Timeout', 'Login request timed out after 15 seconds. Please check your internet connection.');
      } else {
        Alert.alert('Error', `Network error: ${error.message || 'Please try again.'}`);
      }
    } finally {
      console.log('Finally block - setting loading to false');
      setLoading(false);
    }
  };

  if (checkingAuth) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color="#2563eb" />
        <Text style={styles.loadingText}>Loading...</Text>
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView 
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.keyboardView}
      >
        <View style={styles.content}>
          <View style={styles.header}>
            <View style={styles.logoContainer}>
              <View style={styles.logoPlaceholder}>
                <Text style={styles.logoText}>GeoProx</Text>
                <Text style={styles.logoSubtext}>COORDINATES TO CLARITY</Text>
              </View>
            </View>
            <Text style={styles.subtitle}>Mobile Site Inspection</Text>
          </View>

          <View style={styles.form}>
            <Text style={styles.label}>Username</Text>
            <TextInput
              style={styles.input}
              value={username}
              onChangeText={setUsername}
              placeholder="Enter your username"
              placeholderTextColor="#6b7280"
              autoCapitalize="none"
              autoCorrect={false}
            />

            <Text style={styles.label}>Password</Text>
            <TextInput
              style={styles.input}
              value={password}
              onChangeText={setPassword}
              placeholder="Enter your password"
              placeholderTextColor="#6b7280"
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
            />

            <TouchableOpacity 
              style={[styles.loginButton, loading && styles.buttonDisabled]}
              onPress={handleLogin}
              disabled={loading}
            >
              {loading ? (
                <ActivityIndicator size="small" color="#ffffff" />
              ) : (
                <Text style={styles.loginButtonText}>Login</Text>
              )}
            </TouchableOpacity>

            <View style={styles.demoCredentials}>
              <Text style={styles.demoTitle}>Production Credentials:</Text>
              <Text style={styles.demoText}>Username: EXPOTEST</Text>
              <Text style={styles.demoText}>Password: EXPOTEST!!</Text>
            </View>
          </View>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f8fafc',
  },
  keyboardView: {
    flex: 1,
  },
  content: {
    flex: 1,
    padding: 24,
    justifyContent: 'center',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#f8fafc',
  },
  loadingText: {
    marginTop: 16,
    fontSize: 16,
    color: '#6b7280',
  },
  header: {
    alignItems: 'center',
    marginBottom: 48,
  },
  title: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#1f2937',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: '#6b7280',
  },
  form: {
    backgroundColor: '#ffffff',
    borderRadius: 12,
    padding: 24,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.1,
    shadowRadius: 3.84,
    elevation: 5,
  },
  label: {
    fontSize: 16,
    fontWeight: '600',
    color: '#374151',
    marginBottom: 8,
  },
  input: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontSize: 16,
    backgroundColor: '#f9fafb',
    marginBottom: 20,
    color: '#1f2937',
  },
  loginButton: {
    backgroundColor: '#2563eb',
    borderRadius: 8,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 8,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  loginButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  demoCredentials: {
    marginTop: 24,
    padding: 16,
    backgroundColor: '#f3f4f6',
    borderRadius: 8,
  },
  demoTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#4b5563',
    marginBottom: 8,
  },
  demoText: {
    fontSize: 14,
    color: '#6b7280',
    marginBottom: 4,
  },
  logoContainer: {
    alignItems: 'center',
    marginBottom: 16,
  },
  logoPlaceholder: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#1f2937',
    paddingHorizontal: 32,
    paddingVertical: 20,
    borderRadius: 12,
    minWidth: 200,
  },
  logoText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#ffffff',
    letterSpacing: 2,
  },
  logoSubtext: {
    fontSize: 14,
    color: '#fbbf24',
    marginTop: 4,
    letterSpacing: 1.5,
    fontWeight: '600',
  },
});