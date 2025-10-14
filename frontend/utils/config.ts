const fallbackUrl = 'https://epxpzcj3ma.eu-west-1.awsapprunner.com';

export const API_BASE_URL = process.env.EXPO_PUBLIC_BACKEND_URL || fallbackUrl;

if (!process.env.EXPO_PUBLIC_BACKEND_URL) {
  console.warn(
    `EXPO_PUBLIC_BACKEND_URL is not set. Falling back to App Runner URL: ${fallbackUrl}`,
  );
}
