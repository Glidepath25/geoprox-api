import * as SecureStore from 'expo-secure-store';

const ACCESS_TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const TOKEN_EXPIRY_KEY = 'token_expiry';
const REFRESH_EXPIRY_KEY = 'refresh_expiry';

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
      SecureStore.setItemAsync(ACCESS_TOKEN_KEY, accessToken),
      SecureStore.setItemAsync(REFRESH_TOKEN_KEY, refreshToken),
      SecureStore.setItemAsync(TOKEN_EXPIRY_KEY, accessExpiry.toString()),
      SecureStore.setItemAsync(REFRESH_EXPIRY_KEY, refreshExpiry.toString()),
    ]);
  },

  // Get access token
  async getAccessToken(): Promise<string | null> {
    return await SecureStore.getItemAsync(ACCESS_TOKEN_KEY);
  },

  // Get refresh token
  async getRefreshToken(): Promise<string | null> {
    return await SecureStore.getItemAsync(REFRESH_TOKEN_KEY);
  },

  // Check if access token is expired or about to expire (within 5 minutes)
  async isAccessTokenExpired(): Promise<boolean> {
    const expiry = await SecureStore.getItemAsync(TOKEN_EXPIRY_KEY);
    if (!expiry) return true;
    
    const expiryTime = parseInt(expiry);
    const now = Date.now();
    const fiveMinutes = 5 * 60 * 1000;
    
    return now >= (expiryTime - fiveMinutes);
  },

  // Check if refresh token is expired
  async isRefreshTokenExpired(): Promise<boolean> {
    const expiry = await SecureStore.getItemAsync(REFRESH_EXPIRY_KEY);
    if (!expiry) return true;
    
    const expiryTime = parseInt(expiry);
    return Date.now() >= expiryTime;
  },

  // Clear all tokens
  async clearTokens(): Promise<void> {
    await Promise.all([
      SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY),
      SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY),
      SecureStore.deleteItemAsync(TOKEN_EXPIRY_KEY),
      SecureStore.deleteItemAsync(REFRESH_EXPIRY_KEY),
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
