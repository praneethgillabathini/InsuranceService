# ----- Build Stage -----
FROM node:18-alpine AS builder

WORKDIR /app

# Copy dependency definition files
COPY package.json package-lock.json ./

# Cleanly install node modules
RUN npm ci

# Copy source code and perform the production build
COPY . .
RUN npm run build

# ----- Serve Stage -----
# Use Nginx alpine version to minimize the image size
FROM nginx:alpine

# Copy the built React app from the builder stage
COPY --from=builder /app/build /usr/share/nginx/html

# Copy custom Nginx configuration to support client-side routing
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port
EXPOSE 80

# Run Nginx in the foreground
CMD ["nginx", "-g", "daemon off;"]
