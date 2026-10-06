package api

import (
	"encoding/json"
	"net/http"

	"acme/clowder-ai/src/auth"
)

// LoginHandler 只做参数校验与转发,业务逻辑在 auth 包。
func LoginHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Email    string `json:"email"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"bad_request"}`, http.StatusBadRequest)
		return
	}
	if req.Email == "" || req.Password == "" {
		http.Error(w, `{"error":"missing_fields"}`, http.StatusBadRequest)
		return
	}
	res := auth.Login(req.Email, req.Password)
	if res.Code == 401 {
		http.Error(w, `{"error":"invalid_credentials"}`, http.StatusUnauthorized)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(res)
}