import * as SecureStore from 'expo-secure-store';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';

const ACCESS_TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const TOKEN_EXPIRY_KEY = 'token_expiry';
const REFRESH_EXPIRY_KEY = 'refresh_expiry';

// Use SecureStore for native, AsyncStorage for web
const isWeb = Platform.OS === 'web';

const storage = {
  async setItem(key: string, value: string): Promise<void> {
    if (isWeb) {
      await AsyncStorage.setItem(key, value);
    } else {
      await SecureStore.setItemAsync(key, value);
    }
  },
  
  async getItem(key: string): Promise<string | null> {
    if (isWeb) {
      return await AsyncStorage.getItem(key);
    } else {
      return await SecureStore.getItemAsync(key);
    }
  },
  
  async deleteItem(key: string): Promise<void> {
    if (isWeb) {
      await AsyncStorage.removeItem(key);
    } else {
      await SecureStore.deleteItemAsync(key);
    }
  },
};

export const TokenManager = {
  // Store tokens securely
  async storeTokens(
    accessToken: string,
    refreshToken: string,
    expiresIn: number,
    refreshExpiresIn: number
  ): Promise<void> {
    const accessExpiry = Date.now() + expiresIn * 1000;
    const refreshExpiry = Date.now() + refreshExpiresIn * 1000;

    await Promise.all([
      storage.setItem(ACCESS_TOKEN_KEY, accessToken),
      storage.setItem(REFRESH_TOKEN_KEY, refreshToken),
      storage.setItem(TOKEN_EXPIRY_KEY, accessExpiry.toString()),
      storage.setItem(REFRESH_EXPIRY_KEY, refreshExpiry.toString()),
    ]);
  },

  // Get access token
  async getAccessToken(): Promise<string | null> {
    return await storage.getItem(ACCESS_TOKEN_KEY);
  },

  // Get refresh token
  async getRefreshToken(): Promise<string | null> {
    return await storage.getItem(REFRESH_TOKEN_KEY);
  },

  // Check if access token is expired or about to expire (within 5 minutes)
  async isAccessTokenExpired(): Promise<boolean> {
    const expiry = await storage.getItem(TOKEN_EXPIRY_KEY);
    if (!expiry) return true;
    
    const expiryTime = parseInt(expiry);
    const now = Date.now();
    const fiveMinutes = 5 * 60 * 1000;
    
    return now >= (expiryTime - fiveMinutes);
  },

  // Check if refresh token is expired
  async isRefreshTokenExpired(): Promise<boolean> {
    const expiry = await storage.getItem(REFRESH_EXPIRY_KEY);
    if (!expiry) return true;
    
    const expiryTime = parseInt(expiry);
    return Date.now() >= expiryTime;
  },

  // Clear all tokens
  async clearTokens(): Promise<void> {
    await Promise.all([
      storage.deleteItem(ACCESS_TOKEN_KEY),
      storage.deleteItem(REFRESH_TOKEN_KEY),
      storage.deleteItem(TOKEN_EXPIRY_KEY),
      storage.deleteItem(REFRESH_EXPIRY_KEY),
    ]);
  },

  // Refresh access token
  async refreshAccessToken(apiUrl: string): Promise<boolean> {
    try {
      const refreshToken = await this.getRefreshToken();
      if (!refreshToken) {
        return false;
      }

      const response = await fetch(`${apiUrl}/api/mobile/auth/refresh`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (response.ok) {
        const data = await response.json();
        await this.storeTokens(
          data.access_token,
          data.refresh_token,
          data.expires_in,
          data.refresh_expires_in
        );
        return true;
      }

      return false;
    } catch (error) {
      console.error('Token refresh error:', error);
      return false;
    }
  },
};
