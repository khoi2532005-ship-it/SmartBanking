using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Json;
using System.Threading.Tasks;

namespace SmartBanking.Database.Service
{
    public class DatabaseClient : IDatabaseClient
    {
        private readonly HttpClient _http;

        public DatabaseClient(HttpClient http)
        {
            _http = http;
        }

        public async Task<IEnumerable<Dictionary<string, object>>> GetLoansAsync(Dictionary<string, string>? filters = null)
        {
            var url = "/loans";
            if (filters != null && filters.Any())
            {
                url += "?" + string.Join("&", filters.Select(kv => $"{Uri.EscapeDataString(kv.Key)}={Uri.EscapeDataString(kv.Value)}"));
            }

            var resp = await _http.GetFromJsonAsync<IEnumerable<Dictionary<string, object>>>(url);
            return resp ?? Enumerable.Empty<Dictionary<string, object>>();
        }

        public async Task<Dictionary<string, object>?> GetLoanAsync(int loanId)
        {
            return await _http.GetFromJsonAsync<Dictionary<string, object>>($"/loans/{loanId}");
        }

        public async Task<IEnumerable<Dictionary<string, object>>> GetTransactionsAsync(Dictionary<string, string>? filters = null)
        {
            var url = "/transactions";
            if (filters != null && filters.Any())
            {
                url += "?" + string.Join("&", filters.Select(kv => $"{Uri.EscapeDataString(kv.Key)}={Uri.EscapeDataString(kv.Value)}"));
            }

            var resp = await _http.GetFromJsonAsync<IEnumerable<Dictionary<string, object>>>(url);
            return resp ?? Enumerable.Empty<Dictionary<string, object>>();
        }

        public async Task<Dictionary<string, object>?> GetTransactionAsync(int transactionId)
        {
            return await _http.GetFromJsonAsync<Dictionary<string, object>>($"/transactions/{transactionId}");
        }
    }
}
