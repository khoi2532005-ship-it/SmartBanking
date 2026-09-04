using System.Collections.Generic;
using System.Threading.Tasks;

namespace SmartBanking.Database.Service
{
    public interface IDatabaseClient
    {
        Task<IEnumerable<Dictionary<string, object>>> GetLoansAsync(Dictionary<string, string>? filters = null);
        Task<Dictionary<string, object>?> GetLoanAsync(int loanId);
        Task<IEnumerable<Dictionary<string, object>>> GetTransactionsAsync(Dictionary<string, string>? filters = null);
        Task<Dictionary<string, object>?> GetTransactionAsync(int transactionId);
    }
}
